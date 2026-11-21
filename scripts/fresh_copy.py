"""Starts the zip the way a lecturer will: in another folder, with no Node.js, no Gemini key and none of your own files.

    run.bat fresh                   the newest zip in ..\\submission
    run.bat fresh PATH.zip          a particular zip
    run.bat fresh --quick           only unpack it and do the first run (no check of the running app afterwards)
    run.bat fresh --keep            keep the unpacked folder (its place is said at the end) instead of deleting it
    run.bat fresh --photos DIR      use the photos in DIR for the check (default: ..\\test-photos)
    run.bat fresh --folder DIR      unpack under DIR (a short path such as C:\\kf avoids Windows' 260-character limit)
    python scripts/fresh_copy.py ...   the same from any terminal

What it does, in order:
    1. looks at the zip again from the outside (nothing private in it, every needed file in it, the website counts as current)
    2. unpacks it into a new temporary folder. Nothing of this project folder is used: not backend\\.env, not the packages,
       not the built website, not the hand model.
    3. hides Node.js: every folder that holds node or npm is taken out of PATH for what follows, and the Gemini key and any
       other setting of yours are taken out of the environment
    4. does the first run, like a lecturer double-clicking run.bat: it makes the private Python environment, installs every
       package from the internet (this takes a few minutes and about 700 MB), and uses the website that is in the zip
    5. unless --quick, runs  scripts\\preflight.py  of that copy (its own check of the running app, with your photos)
    6. deletes the copy

It ends with  RESULT: PASS  or  RESULT: FAIL. The check of the copy is saved as  ..\\debug\\fresh\\preflight.txt . It describes
your photos in words, so never commit it. Your photos only go to the copy, on this computer, which keeps nothing.
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

if hasattr(sys.stdout, 'reconfigure'):  # a Windows console may not speak UTF-8; never let a print crash the check
    sys.stdout.reconfigure(errors='replace')

import package

PREPARE_SECONDS = 40 * 60  # a first run on a slow connection
PREFLIGHT_SECONDS = 20 * 60
#: the settings of this computer that a lecturer's computer does not have (a key, a model path, a Python environment)
DROP_NAMES = frozenset({'APP_ENV', 'SITE_DIR', 'ANALYSIS_MODE', 'HAND_MODEL', 'HOST', 'PORT', 'COOKIE_SECURE', 'VIRTUAL_ENV', 'STAGE_PAUSE_MS'})
DROP_PREFIXES = ('KIRO_', 'GEMINI_', 'GOOGLE_', 'PYTHON')
BUILT_LINE = 'The website is already built and up to date'
READY_LINE = 'Everything is installed and built'


def say(text: str = '') -> None:
    print(text, flush=True)


# ------------------------------------------------------------------ the pieces


def newest_zip(folder: Path) -> Path | None:
    """The zip that package.py made last (its name holds the date and time)."""
    found = sorted(folder.glob(f'{package.INSIDE}-*.zip'), key=lambda p: (p.stat().st_mtime, p.name))
    return found[-1] if found else None


def without_node(path: str, which=shutil.which) -> tuple[str, list[str]]:
    """PATH without any folder that holds node or npm. Returns the new PATH and the folders that were taken out."""
    kept, removed = [], []
    for folder in path.split(os.pathsep):
        if not folder:  # an empty entry means "the folder I am in", which is not where programs are kept
            continue
        if which('node', path=folder) or which('npm', path=folder):
            removed.append(folder)
        else:
            kept.append(folder)
    return os.pathsep.join(kept), removed


def clean_env(base: dict[str, str], path: str) -> dict[str, str]:
    """The environment of a computer that has never seen this project: no key, no settings, no Python environment, no Node.js."""
    env = {k: v for k, v in base.items() if k.upper() not in DROP_NAMES and not k.upper().startswith(DROP_PREFIXES)}
    env['PATH'] = path
    env['PYTHONUTF8'] = '1'
    return env


def unpack(archive: Path, destination: Path) -> int:
    """Unpacks the zip into `destination` and returns how many files that made."""
    with zipfile.ZipFile(archive) as z:
        package.safe_extract(z, destination)
        return sum(1 for i in z.infolist() if not i.is_dir())


def venv_python(copy: Path) -> Path:
    return copy / 'backend' / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def first_run_command(copy: Path, *, windows: bool | None = None) -> list[str]:
    """What a lecturer does: double-click run.bat. Here it also stops after the preparation, so that no server is left running."""
    if windows if windows is not None else os.name == 'nt':
        return ['cmd', '/c', 'run.bat', '--prepare-only']
    return [sys.executable, str(copy / 'scripts' / 'serve.py'), '--prepare-only']


def kill_tree(process: subprocess.Popen) -> None:
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, check=False)
    else:
        process.kill()


def stream(cmd: list[str], *, cwd: Path, env: dict[str, str], seconds: int, show=lambda line: True) -> tuple[int, list[str]]:
    """Runs a command, shows the lines that `show` accepts as they come, and returns (exit code, every line).
    A command that is still running after `seconds` is stopped, and that is said in the last line."""
    process = subprocess.Popen(
        cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding='utf-8', errors='replace', bufsize=1,
    )
    too_long = threading.Event()

    def stop() -> None:
        too_long.set()
        kill_tree(process)

    watchdog = threading.Timer(seconds, stop)
    watchdog.start()
    lines: list[str] = []
    try:
        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.rstrip('\r\n')
            lines.append(line)
            if show(line):
                say('      ' + line[:150])
        code = process.wait()
    finally:
        watchdog.cancel()
    if too_long.is_set():
        lines.append(f'(stopped: it had not finished after {seconds // 60} minutes)')
        code = code or 1
    return code, lines


def worth_showing_while_installing(line: str) -> bool:
    low = line.lower()
    return line.startswith(('[', 'Collecting ', 'Successfully installed', 'Everything is installed')) or any(w in low for w in ('error', 'failed', 'could not', 'no matching'))


def delete_folder(folder: Path, *, tries: int = 5, pause: float = 2.0) -> bool:
    """Deletes the copy. Windows refuses to delete a read-only file (that is undone first) and a file that anti-virus software
    is looking at (that is tried again a few times). True when the folder is gone."""

    def make_writable(function, path, _error):
        try:
            os.chmod(path, stat.S_IWRITE)
            function(path)
        except OSError:
            pass  # the next round tries again

    for attempt in range(tries):
        shutil.rmtree(folder, onexc=make_writable)
        if not folder.exists():
            return True
        if attempt < tries - 1:
            time.sleep(pause)
    return False


# ------------------------------------------------------------------ the run


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description='Starts the zip the way a lecturer will.')
    parser.add_argument('zip', nargs='?', default=None, help='the zip to start (default: the newest in ..\\submission)')
    parser.add_argument('--quick', action='store_true', help='only unpack it and do the first run')
    parser.add_argument('--keep', action='store_true', help='keep the unpacked folder')
    parser.add_argument('--photos', default=None, help='the folder with your test photos (default: ..\\test-photos)')
    parser.add_argument('--folder', default=None, help='unpack under this folder (default: the temporary folder)')
    args = parser.parse_args(argv)

    started = time.monotonic()
    results: list[str] = []

    def line(status: str, name: str, note: str) -> None:
        results.append(status)
        say(f'  {status}  {name}   [{note}]')

    def finish() -> int:
        failed = 'FAIL' in results
        say(f'\nRESULT: {"FAIL" if failed else "PASS"}   ({(time.monotonic() - started) / 60:.1f} minutes)')
        return 1 if failed else 0

    say('\nKiro AI: starting the zip the way a lecturer will\n')
    archive = Path(args.zip) if args.zip else newest_zip(ROOT.parent / 'submission')
    if archive is None or not archive.is_file():
        line('FAIL', 'the zip', f'there is no zip to start{"" if args.zip else " in " + str(ROOT.parent / "submission")}. Run  run.bat package  first')
        return finish()
    say(f'  zip     {archive}  ({package.megabytes(archive.stat().st_size)})')

    problems = package.check_zip(archive)
    if problems:
        line('FAIL', 'the zip, looked at again', problems[0])
        for problem in problems[1:5]:
            say(f'        {problem}')
        return finish()
    line('PASS', 'the zip, looked at again', 'nothing private in it, every needed file in it, and the website in it counts as up to date')

    parent = Path(args.folder) if args.folder else None
    if parent:
        parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix='kiro-fresh-', dir=parent))
    copy = scratch / package.INSIDE
    say(f'  copy    {copy}')
    try:
        try:
            count = unpack(archive, scratch)
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            line('FAIL', 'unpacked', str(error))
            return finish()
        line('PASS', 'unpacked', f'{count} files, in a new folder')
        for private in ('backend/.env', '.env', '.env.local'):
            if (copy / private).exists():
                line('FAIL', 'unpacked', f'{private} is in the copy')
                return finish()

        path, hidden = without_node(os.environ.get('PATH', ''))
        if shutil.which('node', path=path) or shutil.which('npm', path=path):
            line('FAIL', 'Node.js hidden', 'node or npm is still found after taking its folders out of PATH')
            return finish()
        env = clean_env(dict(os.environ), path)
        line('PASS', 'Node.js hidden', f'taken out of PATH: {", ".join(hidden)}' if hidden else 'Node.js is not on this computer at all')

        say('\n  First run, as a lecturer would do it. It installs every package, so it takes a few minutes...\n')
        began = time.monotonic()
        code, lines = stream(first_run_command(copy), cwd=copy, env=env, seconds=PREPARE_SECONDS, show=worth_showing_while_installing)
        took = f'{(time.monotonic() - began) / 60:.1f} minutes'
        text = '\n'.join(lines)
        if code != 0:
            line('FAIL', 'first run', f'it stopped with code {code} after {took}. The last lines:')
            for last in [x for x in lines if x.strip()][-12:]:
                say('        ' + last[:150])
            say('        If these lines mention a path that is too long, or a file that cannot be found, unpack in a shorter place:  run.bat fresh --folder C:\\kf')
            return finish()
        if BUILT_LINE not in text:
            line('FAIL', 'first run', f'it did not use the website that is in the zip ("{BUILT_LINE}" is missing), so it would need Node.js. Run  run.bat package  again')
            return finish()
        if READY_LINE not in text:
            line('FAIL', 'first run', f'it ended without saying "{READY_LINE}"')
            return finish()
        line('PASS', 'first run', f'the packages installed and the website used as it was built, with no Node.js ({took})')

        if args.quick:
            say('\n  (--quick: the copy was not started.)')
            return finish()

        photos = Path(args.photos) if args.photos else ROOT.parent / 'test-photos'
        out = ROOT.parent / 'debug' / 'fresh'
        say('\n  Now the copy checks itself (scripts\\preflight.py, the same check you run), with no key:\n')
        code, lines = stream(
            [str(venv_python(copy)), str(copy / 'scripts' / 'preflight.py'), '--no-gemini', '--photos', str(photos), '--out', str(out)],
            cwd=copy, env=env, seconds=PREFLIGHT_SECONDS,
        )
        result = next((x.strip() for x in reversed(lines) if x.strip().startswith('RESULT:')), 'no RESULT line')
        if code != 0:
            line('FAIL', 'the copy checks itself', f'{result} (exit code {code}); the lines marked FAIL above say what is wrong')
            return finish()
        warns = sum(1 for x in lines if x.startswith('  WARN'))
        line('PASS', 'the copy checks itself', f'{result}{f", with {warns} warning(s)" if warns else ""}; saved as {out / "preflight.txt"}')
        return finish()
    finally:
        if args.keep:
            say(f'\n  The copy was kept: {copy}')
            say('  To try it by hand, open that folder and double-click run.bat. Delete the folder when you are done.')
        elif delete_folder(scratch):
            say('\n  The copy was deleted.')
        else:
            say(f'\n  The copy could not be deleted completely. Delete this folder yourself: {scratch}')


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
