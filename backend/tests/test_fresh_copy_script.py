"""scripts/fresh_copy.py: the zip, started the way a lecturer will start it. The real thing installs every package from the internet, which
a test cannot do, so a small stand-in project goes through the real steps: unpacking, taking Node.js and the key out of the
environment, running the first run and the project's own check as separate programs, and deleting the copy."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
import time
import zipfile
from pathlib import Path

import pytest
from zip_helpers import SOURCES, build_site, write

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
SCRIPT = SCRIPTS / 'fresh_copy.py'

# A key-shaped value, built in pieces so that the scan of this very folder does not (rightly) flag this file.
KEY = 'AIza' + 'SyDq8Zr3Xk1Lm9Wv2Bn7Ht4Jc6Pf0Gs5Yua'


@pytest.fixture
def fc():
    spec = importlib.util.spec_from_file_location('fresh_copy_under_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules['fresh_copy_under_test'] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop('fresh_copy_under_test', None)


# ------------------------------------------------------------------ a stand-in project: the same lines, none of the work

OK_SERVE = """
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
print('[1/4] The private Python environment is ready.')
print('[2/4] The Python packages are installed.')
print('[3/4] The website is already built and up to date.')
python = root / 'backend' / '.venv' / 'bin' / 'python'
python.parent.mkdir(parents=True, exist_ok=True)
if not python.exists():
    python.symlink_to(sys.executable)
print('Everything is installed and built. (--prepare-only: not starting the server.)')
"""

OK_PREFLIGHT = """
import json
import os
import shutil
import sys
from pathlib import Path

args = sys.argv[1:]
out = Path(args[args.index('--out') + 1])
out.mkdir(parents=True, exist_ok=True)
(out / 'seen.json').write_text(json.dumps({
    'argv': args, 'key': 'GEMINI_API_KEY' in os.environ, 'google': 'GOOGLE_API_KEY' in os.environ, 'child': 'KIRO_SERVE_CHILD' in os.environ,
    'node': shutil.which('node'), 'npm': shutil.which('npm'), 'cwd': os.getcwd(), 'utf8': os.environ.get('PYTHONUTF8'),
}))
print('  PASS  Python   [fine]')
print('  WARN  photos   [only one pair]')
print('  WARN  Gemini key   [no key]')
print()
print('RESULT: PASS')
"""


def make_zip(fc, tmp_path, monkeypatch, *, serve: str = OK_SERVE, preflight: str = OK_PREFLIGHT, extra: dict | None = None) -> Path:
    """A zip of a stand-in project, in the folder where package.py would have put it. Returns the zip."""
    pk = fc.package
    root = tmp_path / 'project' / 'kiro-ai'
    write(root, {**SOURCES, 'scripts/serve.py': serve, 'scripts/preflight.py': preflight, **(extra or {})})
    build_site(pk, root)
    archive = pk.build_zip(pk.make_plan(root, include_model=False), tmp_path / 'project' / 'submission', stamp='20261119-120000')
    monkeypatch.setattr(fc, 'ROOT', root)
    return archive


@pytest.fixture
def fake_node(tmp_path, monkeypatch):
    """Node.js on this computer: a folder on PATH with node and npm in it."""
    folder = tmp_path / 'nodejs'
    folder.mkdir()
    for name in ('node', 'npm'):
        (folder / name).write_text('#!/bin/sh\n')
        (folder / name).chmod(0o755)
    monkeypatch.setenv('PATH', os.pathsep.join([str(folder), os.environ['PATH']]))
    return folder


def run(fc, capsys, *argv):
    code = fc.main(list(argv))
    return code, capsys.readouterr().out


def seen(tmp_path) -> dict:
    return json.loads((tmp_path / 'project' / 'debug' / 'fresh' / 'seen.json').read_text())


# ------------------------------------------------------------------ the pieces


def test_the_newest_zip_is_the_one_made_last(fc, tmp_path):
    assert fc.newest_zip(tmp_path) is None
    for name, age in (('kiro-ai-20261101-100000.zip', 300), ('kiro-ai-20261119-100000.zip', 100), ('kiro-ai-20261110-100000.zip', 200), ('notes.zip', 0)):
        path = tmp_path / name
        path.write_bytes(b'PK')
        os.utime(path, (time.time() - age, time.time() - age))
    assert fc.newest_zip(tmp_path).name == 'kiro-ai-20261119-100000.zip'


def test_node_is_taken_out_of_path_folder_by_folder(fc):
    holds = {'/opt/nodejs': {'node', 'npm'}, '/opt/other': {'npm'}, '/usr/bin': {'python3'}, '/opt/py': {'python'}}

    def which(name, path):
        return f'{path}/{name}' if name in holds.get(path, ()) else None

    kept, removed = fc.without_node(os.pathsep.join(['/opt/nodejs', '/usr/bin', '', '/opt/other', '/opt/py']), which=which)
    assert removed == ['/opt/nodejs', '/opt/other'] and kept == os.pathsep.join(['/usr/bin', '/opt/py'])


def test_the_environment_is_that_of_a_computer_that_has_never_seen_the_project(fc):
    base = {
        'PATH': '/with/node', 'SystemRoot': 'C:\\Windows', 'TEMP': '/tmp', 'HOME': '/home/me',
        'GEMINI_API_KEY': KEY, 'gemini_model': 'x', 'GOOGLE_API_KEY': KEY, 'GOOGLE_GEMINI_BASE_URL': 'http://x',
        'KIRO_SERVE_CHILD': '1', 'VIRTUAL_ENV': '/v', 'PYTHONPATH': '/p', 'PYTHONHOME': '/h', 'HAND_MODEL': '/m', 'SITE_DIR': '/s',
        'ANALYSIS_MODE': 'mock', 'APP_ENV': 'test', 'PORT': '1', 'HOST': 'h',
    }
    env = fc.clean_env(base, '/without/node')
    assert env == {'PATH': '/without/node', 'SystemRoot': 'C:\\Windows', 'TEMP': '/tmp', 'HOME': '/home/me', 'PYTHONUTF8': '1'}


def test_the_first_run_is_the_double_click_on_windows_and_serve_py_elsewhere(fc, tmp_path):
    assert fc.first_run_command(tmp_path, windows=True) == ['cmd', '/c', 'run.bat', '--prepare-only']
    assert fc.first_run_command(tmp_path, windows=False) == [sys.executable, str(tmp_path / 'scripts' / 'serve.py'), '--prepare-only']
    assert fc.venv_python(tmp_path).parts[-3:] == ('.venv', 'bin', 'python') or fc.venv_python(tmp_path).parts[-3:] == ('.venv', 'Scripts', 'python.exe')


def test_the_lines_the_check_looks_for_are_the_ones_serve_py_prints(fc):
    source = (SCRIPTS / 'serve.py').read_text(encoding='utf-8')
    assert fc.BUILT_LINE in source and fc.READY_LINE in source


def test_unpacking_counts_the_files_and_refuses_a_name_that_leaves_the_folder(fc, tmp_path):
    good = tmp_path / 'good.zip'
    with zipfile.ZipFile(good, 'w') as z:
        z.writestr('kiro-ai/a.txt', 'a')
        z.writestr('kiro-ai/sub/b.txt', 'b')
    assert fc.unpack(good, tmp_path / 'here') == 2 and (tmp_path / 'here' / 'kiro-ai' / 'sub' / 'b.txt').read_text() == 'b'
    evil = tmp_path / 'evil.zip'
    with zipfile.ZipFile(evil, 'w') as z:
        z.writestr('../evil.txt', 'x')
    with pytest.raises(ValueError, match='outside its folder'):
        fc.unpack(evil, tmp_path / 'there')
    assert not (tmp_path / 'evil.txt').exists()


def test_a_folder_with_read_only_files_is_deleted(fc, tmp_path):
    folder = tmp_path / 'copy'
    (folder / 'sub').mkdir(parents=True)
    locked = folder / 'sub' / 'locked.txt'
    locked.write_text('x')
    locked.chmod(stat.S_IREAD)
    (folder / 'sub').chmod(stat.S_IREAD | stat.S_IEXEC)
    assert fc.delete_folder(folder) is True and not folder.exists()


def test_a_file_that_stays_locked_does_not_crash_the_clean_up_and_is_said_not_deleted(fc, tmp_path, monkeypatch):
    folder = tmp_path / 'copy'
    folder.mkdir()
    (folder / 'locked.dll').write_text('x')
    calls = []

    def locked(path, *, onexc):  # what Windows does while anti-virus software holds a file: it cannot be deleted, however often
        calls.append(path)
        onexc(os.remove, str(folder / 'locked.dll'), PermissionError('in use'))

    monkeypatch.setattr(fc.shutil, 'rmtree', locked)
    monkeypatch.setattr(fc.os, 'remove', lambda path: (_ for _ in ()).throw(PermissionError('in use')))
    assert fc.delete_folder(folder, tries=3, pause=0) is False and len(calls) == 3 and folder.exists()


def test_a_file_that_is_free_the_second_time_is_deleted(fc, tmp_path, monkeypatch):
    folder = tmp_path / 'copy'
    folder.mkdir()
    real = fc.shutil.rmtree
    attempts = []

    def busy_once(path, *, onexc):
        attempts.append(1)
        if len(attempts) == 1:
            return  # the first round: the scanner has it, so nothing goes
        real(path, onexc=onexc)

    monkeypatch.setattr(fc.shutil, 'rmtree', busy_once)
    assert fc.delete_folder(folder, tries=3, pause=0) is True and len(attempts) == 2 and not folder.exists()


def test_a_command_is_followed_line_by_line_and_the_wanted_lines_are_shown(fc, capsys, tmp_path):
    code, lines = fc.stream(
        [sys.executable, '-c', 'print("one"); print("Collecting numpy"); print("two")'],
        cwd=tmp_path, env=os.environ.copy(), seconds=30, show=fc.worth_showing_while_installing,
    )
    assert code == 0 and lines == ['one', 'Collecting numpy', 'two']
    assert capsys.readouterr().out == '      Collecting numpy\n'
    code, _ = fc.stream([sys.executable, '-c', 'raise SystemExit(3)'], cwd=tmp_path, env=os.environ.copy(), seconds=30)
    assert code == 3


def test_a_command_that_runs_too_long_is_stopped_and_that_is_said(fc, tmp_path):
    began = time.monotonic()
    code, lines = fc.stream([sys.executable, '-u', '-c', 'import time; print("started", flush=True); time.sleep(60)'], cwd=tmp_path, env=os.environ.copy(), seconds=1)
    assert time.monotonic() - began < 20 and code != 0 and lines[0] == 'started' and 'stopped' in lines[-1]


# ------------------------------------------------------------------ the whole run, with the stand-in project


def test_a_good_zip_is_started_checked_and_the_copy_deleted(fc, tmp_path, monkeypatch, capsys, fake_node):
    archive = make_zip(fc, tmp_path, monkeypatch)
    monkeypatch.setenv('GEMINI_API_KEY', KEY)
    monkeypatch.setenv('GOOGLE_API_KEY', KEY)
    monkeypatch.setenv('KIRO_SERVE_CHILD', '1')
    photos = tmp_path / 'test-photos'
    code, out = run(fc, capsys, '--folder', str(tmp_path / 'scratch'), '--photos', str(photos))
    assert code == 0 and 'RESULT: PASS' in out and KEY not in out
    for line in ('PASS  the zip, looked at again', 'PASS  unpacked', 'PASS  Node.js hidden', 'PASS  first run', 'PASS  the copy checks itself'):
        assert line in out
    assert str(archive) in out and str(fake_node) in out  # the newest zip was found by itself, and the Node folder was named
    assert 'with 2 warning(s)' in out and 'The copy was deleted' in out
    assert list((tmp_path / 'scratch').iterdir()) == []

    saw = seen(tmp_path)  # what the project's own check saw, from the inside
    assert saw['key'] is False and saw['google'] is False and saw['child'] is False
    assert saw['node'] is None and saw['npm'] is None and saw['utf8'] == '1'
    assert '--no-gemini' in saw['argv'] and saw['argv'][saw['argv'].index('--photos') + 1] == str(photos)
    assert Path(saw['cwd']).name == 'kiro-ai' and 'kiro-fresh-' in saw['cwd']  # the copy, not this folder


def test_quick_only_unpacks_and_does_the_first_run(fc, tmp_path, monkeypatch, capsys):
    make_zip(fc, tmp_path, monkeypatch)
    code, out = run(fc, capsys, '--quick', '--folder', str(tmp_path / 'scratch'))
    assert code == 0 and 'PASS  first run' in out and '--quick' in out and 'the copy checks itself' not in out
    assert not (tmp_path / 'project' / 'debug').exists()


def test_keep_leaves_the_copy_and_says_where(fc, tmp_path, monkeypatch, capsys):
    make_zip(fc, tmp_path, monkeypatch)
    code, out = run(fc, capsys, '--quick', '--keep', '--folder', str(tmp_path / 'scratch'))
    kept = list((tmp_path / 'scratch').iterdir())
    assert code == 0 and len(kept) == 1 and f'The copy was kept: {kept[0] / "kiro-ai"}' in out
    assert (kept[0] / 'kiro-ai' / 'run.bat').is_file() and not (kept[0] / 'kiro-ai' / 'backend' / '.env').exists()


def test_a_named_zip_is_used_instead_of_the_newest(fc, tmp_path, monkeypatch, capsys):
    archive = make_zip(fc, tmp_path, monkeypatch)
    other = archive.with_name('kiro-ai-20270101-000000.zip')
    other.write_bytes(b'not a zip')
    code, out = run(fc, capsys, str(archive), '--quick', '--folder', str(tmp_path / 'scratch'))
    assert code == 0 and str(archive) in out and str(other) not in out


def test_no_zip_says_to_make_one_first(fc, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fc, 'ROOT', tmp_path / 'project' / 'kiro-ai')
    code, out = run(fc, capsys)
    assert code == 1 and 'FAIL  the zip' in out and 'run.bat package' in out and 'RESULT: FAIL' in out


def test_a_zip_with_something_private_in_it_is_refused_before_anything_is_unpacked(fc, tmp_path, monkeypatch, capsys):
    archive = make_zip(fc, tmp_path, monkeypatch)
    with zipfile.ZipFile(archive, 'a') as z:
        z.writestr('kiro-ai/backend/.env', 'GEMINI_API_KEY=' + KEY)
    code, out = run(fc, capsys, '--folder', str(tmp_path / 'scratch'))
    assert code == 1 and 'FAIL  the zip, looked at again' in out and 'backend/.env is a private file' in out and KEY not in out
    assert not (tmp_path / 'scratch').exists() or list((tmp_path / 'scratch').iterdir()) == []


def test_a_first_run_that_fails_shows_the_last_lines_and_still_deletes_the_copy(fc, tmp_path, monkeypatch, capsys):
    broken = "import sys\nprint('[1/4] The private Python environment is ready.')\nprint('ERROR: No matching distribution found for mediapipe')\nsys.exit(1)\n"
    make_zip(fc, tmp_path, monkeypatch, serve=broken)
    code, out = run(fc, capsys, '--folder', str(tmp_path / 'scratch'))
    assert code == 1 and 'FAIL  first run' in out and 'stopped with code 1' in out and 'No matching distribution found for mediapipe' in out
    assert 'run.bat fresh --folder C:\\kf' in out
    assert 'the copy checks itself' not in out and list((tmp_path / 'scratch').iterdir()) == []


def test_a_first_run_that_would_have_built_the_website_is_a_failure(fc, tmp_path, monkeypatch, capsys):
    """If the zip's website were out of date, a computer without Node.js could not start it: that must not pass."""
    would_build = OK_SERVE.replace('The website is already built and up to date.', 'Building the website (first run, or the screens changed)...')
    make_zip(fc, tmp_path, monkeypatch, serve=would_build)
    code, out = run(fc, capsys, '--quick', '--folder', str(tmp_path / 'scratch'))
    assert code == 1 and 'FAIL  first run' in out and 'it would need Node.js' in out


def test_a_first_run_that_does_not_finish_is_a_failure(fc, tmp_path, monkeypatch, capsys):
    unfinished = OK_SERVE.replace("print('Everything is installed and built. (--prepare-only: not starting the server.)')", "print('...')")
    make_zip(fc, tmp_path, monkeypatch, serve=unfinished)
    code, out = run(fc, capsys, '--quick', '--folder', str(tmp_path / 'scratch'))
    assert code == 1 and 'it ended without saying "Everything is installed and built"' in out


def test_a_failing_check_in_the_copy_fails_the_run(fc, tmp_path, monkeypatch, capsys):
    failing = "print('  FAIL  the smoke check   [a page did not load]')\nprint()\nprint('RESULT: FAIL')\nraise SystemExit(1)\n"
    make_zip(fc, tmp_path, monkeypatch, preflight=failing)
    code, out = run(fc, capsys, '--folder', str(tmp_path / 'scratch'))
    assert code == 1 and 'FAIL  the copy checks itself' in out and 'RESULT: FAIL (exit code 1)' in out and 'a page did not load' in out
    assert list((tmp_path / 'scratch').iterdir()) == []


def test_if_node_cannot_be_hidden_the_run_stops_rather_than_pretend(fc, tmp_path, monkeypatch, capsys, fake_node):
    make_zip(fc, tmp_path, monkeypatch)
    monkeypatch.setattr(fc, 'without_node', lambda path: (path, []))  # a folder that could not be taken out
    code, out = run(fc, capsys, '--quick', '--folder', str(tmp_path / 'scratch'))
    assert code == 1 and 'FAIL  Node.js hidden' in out and 'still found' in out and 'first run' not in out.split('FAIL  Node.js hidden')[1]
