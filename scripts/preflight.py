"""Preflight: everything that has to be true before a demonstration, checked in one go.

    run.bat preflight                 Windows (it makes sure the packages are installed first)
    run.bat preflight --no-gemini     do not make the one small request to Google
    run.bat preflight --no-server     only look at the files and settings: do not start the app
    run.bat preflight --photos DIR    read photos from DIR instead of ..\\test-photos
    run.bat preflight --out DIR       keep the text copy somewhere else (default: ..\\debug)
    python scripts/preflight.py ...   the same, from any terminal (use the Python in backend/.venv)

What it checks, in four groups:

    This computer     the Python version, every package at its pinned version, one OpenCV, the hand model (loaded for real),
                      the settings (the key: only "present" or "missing", never the key itself)
    The project       the built website matches its sources, no key or private file is written in the project, git ignores the
                      right folders, every package is pinned, and your test photos (pairs, and photos meant to fail)
    Google            one small request to Gemini, only when a key is set
    The running app   it starts the app by itself on a spare port (your own window is not touched) and runs the whole smoke
                      check against it, then four drills with your real photos: a page closed in the middle of a reading, two
                      browsers reading at once, your bad photos, and Google unreachable (the reading must still finish, with
                      the fixed wording and a plain note). Last, a privacy audit: the app ran with its own empty temporary
                      folder and its log in a file, and after your photos went through it nothing may be found in them
                      (no picture, no file name, no name, no e-mail address), nor any new file in the project folder.

It ends with  RESULT: PASS  or  RESULT: FAIL  (exit code 0 or 1). A line marked WARN is something to know or to do, not a break:
for example a missing Gemini key (the app works without one) or fewer than three photo pairs. Everything it prints is also saved
as  ..\\debug\\preflight.txt  so that nobody has to copy a long screen. That copy says what was found in your photos, in words:
never commit it. Your photos only go to the app on this computer, which keeps nothing, and Google never gets a photo.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import secrets
import shutil
import struct
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import urllib.request
import zipfile
from collections.abc import Callable
from datetime import datetime
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'backend'
SCRIPTS = Path(__file__).resolve().parent
DEBUG = ROOT.parent / 'debug'
TEST_PHOTOS = ROOT.parent / 'test-photos'
SERVE = SCRIPTS / 'serve.py'

sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(BACKEND))

if hasattr(sys.stdout, 'reconfigure'):  # a Windows console may not speak UTF-8; never let a print crash the check
    sys.stdout.reconfigure(errors='replace')

import repo_checks
import serve
import smoke

WIDTH = 100
PHOTO_SUFFIXES = ('.jpg', '.jpeg', '.png')
#: a photo (or folder) with one of these in its name is meant to be refused or warned about
BAD_WORDS = ('bad', 'blur', 'dark', 'error', 'notpalm', 'not-palm', 'not_palm', 'fail')
#: how many pairs and how many error cases the assessment asks for
PAIRS_NEEDED = 3
FIRST_PORT = 8765
#: folders that are not part of the project's own files, when looking for files the app might have written
AUDIT_SKIP = frozenset({'.git', 'node_modules', '.venv', '__pycache__', '.pytest_cache', '.ruff_cache'})
#: what a picture looks like inside a file or a log
IMAGE_SIGNS = (b'\xff\xd8\xff', b'\x89PNG', b'data:image', b'base64,', b'/9j/', b'iVBOR')
#: how long a page closed in the middle of a reading is given to leave nothing behind
CLOSED_PAGE_WAIT = 20.0


# ------------------------------------------------------------------ what is printed


class Report:
    """Everything printed, kept so that a text copy can be saved. The key is never printed."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.counts = {'PASS': 0, 'WARN': 0, 'FAIL': 0}

    def say(self, text: str = '') -> None:
        print(text, flush=True)
        self.lines.append(text)

    def group(self, title: str) -> None:
        self.say()
        self.say(title)

    def note(self, text: str, indent: str = '        ') -> None:
        for line in textwrap.wrap(text, WIDTH, initial_indent=indent, subsequent_indent=indent) or [indent]:
            self.say(line)

    def result(self, status: str, name: str, note: str = '') -> None:
        self.counts[status] += 1
        head = f'  {status:4}  {name}'
        if len(head) + len(note) + 5 <= WIDTH or not note:
            self.say(head + (f'   [{note}]' if note else ''))
        else:
            self.say(head)
            self.note(note, '          ')

    def step(self, name: str, fn: Callable[[], tuple[str, str]]) -> str:
        """Runs one check. `fn` returns (PASS, WARN or FAIL, a short note). A crash in the check is a FAIL, not the end."""
        started = time.monotonic()
        try:
            status, note = fn()
        except Exception as exc:  # noqa: BLE001 (show it, keep going with the other checks)
            status, note = 'FAIL', f'the check itself broke: {type(exc).__name__}: {exc}'
        took = time.monotonic() - started
        self.result(status, name, note + (f' ({took:.0f} s)' if took >= 5 else ''))
        return status

    def text(self) -> str:
        return '\n'.join(self.lines) + '\n'


# ------------------------------------------------------------------ this computer


def pinned(requirements: Path) -> list[tuple[str, str]]:
    """(name, version) for every `name==version` line of a requirements file."""
    found = []
    for line in repo_checks.requirement_lines(requirements):
        if repo_checks.PIN.match(line):
            name, _, version = line.partition('==')
            found.append((name.split('[')[0], version))
    return found


def check_python() -> tuple[str, str]:
    version = '.'.join(str(n) for n in sys.version_info[:3])
    bits = struct.calcsize('P') * 8
    if sys.version_info < serve.MIN_PYTHON:
        return 'FAIL', f'Python {version} is too old: 3.12 or newer is needed. Install it from python.org, delete backend\\.venv and run run.bat again.'
    if bits != 64:
        return 'FAIL', f'this Python is {bits}-bit, and the packages need 64-bit Python. Install 64-bit Python, delete backend\\.venv and run run.bat again.'
    where = 'the private environment backend\\.venv' if serve.inside_project_venv() else 'a Python outside backend\\.venv (run.bat uses the private one)'
    return 'PASS', f'Python {version}, {bits}-bit, in {where}'


def check_packages(requirements: Path = BACKEND / 'requirements.txt') -> tuple[str, str]:
    pins = pinned(requirements)
    missing, different = [], []
    for name, wanted in pins:
        try:
            have = metadata.version(name)
        except metadata.PackageNotFoundError:
            missing.append(name)
            continue
        if have != wanted:
            different.append(f'{name} {have} (wanted {wanted})')
    if missing or different:
        shown = [f'{n} is not installed' for n in missing] + different
        more = f' and {len(shown) - 5} more' if len(shown) > 5 else ''
        return 'FAIL', f'{len(pins) - len(shown)} of {len(pins)} packages are right. {"; ".join(shown[:5])}{more}. run.bat installs them again.'
    return 'PASS', f'{len(pins)} of {len(pins)} packages are installed at the version the tests used'


def check_opencv() -> tuple[str, str]:
    try:
        metadata.version('opencv-python')
    except metadata.PackageNotFoundError:
        pass
    else:
        return 'FAIL', 'both opencv-python and opencv-contrib-python are installed, and they fight over the same files. Delete backend\\.venv and run run.bat again.'
    import cv2

    if not hasattr(cv2, 'ximgproc'):
        return 'WARN', f'OpenCV {cv2.__version__} has no ximgproc part, so the "other creases" are not looked for (the five lines still are)'
    return 'PASS', f'OpenCV {cv2.__version__}, a single package, with the part that finds other creases'


@contextlib.contextmanager
def quiet_native_output():
    """Hides what a library writes straight to the console while it loads (MediaPipe prints its own INFO lines there)."""
    try:
        sys.stderr.flush()
        saved = os.dup(2)
        null = os.open(os.devnull, os.O_WRONLY)
    except OSError:
        yield
        return
    try:
        os.dup2(null, 2)
        yield
    finally:
        os.dup2(saved, 2)
        os.close(saved)
        os.close(null)


def check_model(model: Path) -> tuple[str, str]:
    if not model.is_file():
        return 'WARN', f'{model.name} is not in {model.parent}, so every photo would get a labelled SAMPLE reading. Run  run.bat models  to download it.'
    size = model.stat().st_size
    if size < 1_000_000 or not zipfile.is_zipfile(model):
        return 'FAIL', f'{model.name} is damaged ({size:,} bytes). Delete it and run  run.bat models  again.'
    from app.cv.hand import build_finder

    with quiet_native_output():
        finder = build_finder('real', model)  # loads it for real; raises when it cannot
        finder.close()  # type: ignore[union-attr]
    return 'PASS', f'{model.name}, {size / 1e6:.1f} MB, loads'


def check_settings(settings, env_file: Path = BACKEND / '.env') -> tuple[str, str]:
    where = 'backend\\.env' if env_file.is_file() else 'no backend\\.env file'
    storage_status, storage = storage_check(settings)
    if storage_status == 'FAIL':
        return 'FAIL', f'{where}; {storage}'
    if settings.gemini_api_key:
        return storage_status, f'{where}; the Gemini key is present (never shown); model {', then '.join(settings.gemini_models or [settings.gemini_model])}; analysis mode {settings.analysis_mode}; {storage}'
    return 'WARN', f'{where}; there is no Gemini key, so reports and answers use the fixed wording from the knowledge base. The app works fully without one. {storage[0].upper()}{storage[1:]}.'


def storage_check(settings) -> tuple[str, str]:
    """Where the server will keep accounts, in a few words, and whether that is all right. The Firebase key file is read only to
    see that it can be used (nothing is sent anywhere, and the key itself is never shown)."""
    from app.store.build import check_key

    if settings.storage == 'memory':
        return 'PASS', 'accounts are kept in memory only (STORAGE=memory)'
    if not settings.firebase_key.is_file():
        if settings.storage == 'firestore':
            return 'FAIL', (
                f'STORAGE=firestore, but there is no Firebase key at {settings.firebase_key}, so run.bat would stop. '
                'Put the key there (see the README) or remove the STORAGE line from backend\\.env'
            )
        return 'PASS', 'accounts are kept in memory only (no Firebase key in backend\\secrets)'
    project, problem = check_key(settings)
    if problem and settings.storage == 'firestore':
        return 'FAIL', f'STORAGE=firestore, but the Firebase key cannot be used ({problem}), so run.bat would stop. Make a new key (see the README)'
    if problem:
        return 'WARN', f'the Firebase key cannot be used ({problem}), so accounts are kept in memory only. Make a new key (see the README) and check it with run.bat firebase'
    return 'PASS', f'accounts are kept in the online database, Firebase project {project} (the key is never shown; check the connection with run.bat firebase)'


# ------------------------------------------------------------------ the project


def check_site(site: Path | None = None) -> tuple[str, str]:
    site = site or serve.SITE
    index = site / 'index.html'
    node = shutil.which('node')
    node_text = 'Node.js found' if node else 'Node.js not needed here'
    if not index.is_file():
        if node:
            return 'WARN', 'the website has not been built yet. run.bat builds it the first time you start it.'
        return 'FAIL', 'the website is not built, and this computer has no Node.js to build it. Use the zip that carries the built website.'
    try:
        mock = json.loads((site / 'build-info.json').read_text(encoding='utf-8')).get('mock')
    except (OSError, ValueError):
        mock = None
    if mock is not False:
        return 'FAIL', 'the website in dist-server is the sample-data build (or has no build-info.json), so it never calls the server. Run  run.bat --rebuild'
    if site == serve.SITE and not serve.site_is_current():
        if node:
            return 'WARN', 'the website is older than its sources; run.bat will build it again when you start it'
        return 'WARN', 'the website is older than its sources and this computer has no Node.js: the older build is used (it still works)'
    return 'PASS', f'the website is built from these sources ({node_text})'


def find_pairs(folder: Path) -> tuple[list[tuple[str, Path, Path]], list[Path]]:
    """(good pairs as (name, left, right), photos meant to fail). A file (or a folder) with "bad", "blur", "dark", "error" and the
    like in its name is meant to fail; a file whose name has "left" (or "right") in it is that hand."""
    pairs: list[tuple[str, Path, Path]] = []
    bad: list[Path] = []
    if not folder.is_dir():
        return pairs, bad
    for directory in [folder, *sorted(p for p in folder.rglob('*') if p.is_dir())]:
        images = [p for p in sorted(directory.iterdir()) if p.is_file() and p.suffix.lower() in PHOTO_SUFFIXES]
        meant_to_fail = [p for p in images if any(w in str(p.relative_to(folder)).lower() for w in BAD_WORDS)]
        bad.extend(meant_to_fail)
        good = [p for p in images if p not in meant_to_fail]
        lefts = [p for p in good if 'left' in p.name.lower() and 'right' not in p.name.lower()]
        rights = [p for p in good if 'right' in p.name.lower() and 'left' not in p.name.lower()]
        if lefts and rights:
            pairs.append((directory.name if directory != folder else folder.name, lefts[0], rights[0]))
    return pairs, bad


def check_photos(folder: Path) -> tuple[str, str]:
    pairs, bad = find_pairs(folder)
    if not folder.is_dir():
        return 'WARN', f'{folder} does not exist. The assessment asks for {PAIRS_NEEDED} consenting left/right pairs and 1 photo that fails.'
    names = ', '.join(name for name, _, _ in pairs) or 'none'
    note = f'{len(pairs)} pair(s) ({names}), {len(bad)} photo(s) meant to fail'
    lacking = []
    if len(pairs) < PAIRS_NEEDED:
        lacking.append(f'{PAIRS_NEEDED - len(pairs)} more pair(s) of left and right (the brief asks for {PAIRS_NEEDED})')
    if not bad:
        lacking.append('a photo that should fail (blurred, dark, or not a palm), with "bad" or "blur" in its name')
    if lacking:
        return 'WARN', f'{note}. Still needed: {" and ".join(lacking)}.'
    return 'PASS', note


# ------------------------------------------------------------------ Google


def check_google(settings, report: Report) -> tuple[str, str]:
    """One small request, made exactly as the app makes its own. Only the word "ready" is asked for: nothing about anyone."""
    import check_gemini

    from app.llm.gemini import ModelUnavailable, service_from_settings

    service = service_from_settings(settings)
    try:
        seconds, answered_by = check_gemini.tiny_answer(service)
    except ModelUnavailable as exc:
        advice = check_gemini.ADVICE.get(exc.kind, '')
        text = f'[{exc.kind}] {exc.reason}. {advice}'
        if exc.kind in ('overloaded', 'rate_limited', 'timeout', 'error'):  # temporary: the app falls back to the fixed wording
            return 'WARN', f'{text} Meanwhile the app writes with the fixed wording, which always works.'
        return 'FAIL', text
    again = ' (Google was busy once, so the request was repeated)' if service.repeats else ''
    models = settings.gemini_models or [settings.gemini_model]
    instead = f' ({models[0]} could not answer just now, so the next model did, as the app does)' if answered_by and answered_by != models[0] else ''
    spare = f'; if it is busy the app asks: {", ".join(models[1:])}' if len(models) > 1 else ''
    return 'PASS', f'{answered_by or models[0]} answered in {seconds:.1f} s{again}{instead}{spare}'


# ------------------------------------------------------------------ the app, running


def free_port(start: int = FIRST_PORT) -> int:
    for port in range(start, start + 50):
        if not serve.port_in_use(port):
            return port
    raise RuntimeError(f'no free port between {start} and {start + 49}')


class RunningApp:
    """The app as its own process on a spare port, with an empty private temporary folder and its log in a file. Both are looked at
    afterwards: a photo, a file name or a name that reached the log or the temporary folder would be a leak."""

    def __init__(self, folder: Path, *, extra_env: dict[str, str] | None = None) -> None:
        self.folder = folder
        self.tmp = folder / 'tmp'
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.log_path = folder / 'server.log'
        self.port = free_port()
        self.base = f'http://{serve.HOST}:{self.port}'
        self.env = {
            **os.environ,
            'TMP': str(self.tmp),
            'TEMP': str(self.tmp),
            'TMPDIR': str(self.tmp),
            'PYTHONUTF8': '1',
            'PYTHONIOENCODING': 'utf-8',
            'PYTHONUNBUFFERED': '1',
            serve.CHILD_FLAG: '1',
            # a check never writes its made-up accounts to the real database, even when the Firebase key is in place
            'STORAGE': 'memory',
            **(extra_env or {}),
        }
        self.proc: subprocess.Popen | None = None
        self.log_file = None

    def start(self) -> None:
        self.log_file = self.log_path.open('wb')
        command = [sys.executable, str(SERVE), '--no-browser', '--no-build', '--port', str(self.port)]
        self.proc = subprocess.Popen(command, cwd=ROOT, env=self.env, stdout=self.log_file, stderr=subprocess.STDOUT)

    def wait_until_up(self, timeout: float = 150.0) -> None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.proc is not None and self.proc.poll() is not None:
                raise RuntimeError(f'the app stopped while starting (code {self.proc.returncode}). Its last lines:\n{self.tail()}')
            if smoke.kiro_at(self.base):
                return
            time.sleep(0.5)
        raise RuntimeError(f'the app did not answer within {timeout:.0f} s. Its last lines:\n{self.tail()}')

    def tail(self, lines: int = 12) -> str:
        return '\n'.join(self.log_bytes().decode('utf-8', errors='replace').splitlines()[-lines:])

    def log_bytes(self) -> bytes:
        try:
            return self.log_path.read_bytes()
        except OSError:
            return b''

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            stop_tree(self.proc)
        if self.log_file is not None:
            self.log_file.close()
            self.log_file = None


def stop_tree(process: subprocess.Popen, *, windows: bool | None = None) -> None:
    """Stops the app and anything it started. On Windows the Python of a private environment is a small launcher that starts the
    real interpreter, and ending the launcher alone would leave the server running (holding its port and its log file)."""
    if windows if windows is not None else os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, check=False)
        process.wait(10)
        return
    process.terminate()
    try:
        process.wait(20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(10)


# ------------------------------------------------------------------ the drills


class Photos:
    """What the drills read: your first real pair when there is one, otherwise the made-up drawings (marked as samples)."""

    def __init__(self, pair: tuple[Path, Path] | None) -> None:
        self.real = pair is not None
        if pair is not None:
            self.data = {'left': pair[0].read_bytes(), 'right': pair[1].read_bytes()}
            self.fields: dict[str, str] = {}
        else:
            self.data = {side: (smoke.PHOTOS / f'sample-{side}.jpg').read_bytes() for side in ('left', 'right')}
            self.fields = {'leftSample': '1', 'rightSample': '1'}

    def files(self, name: str) -> dict:
        return {side: (f'{name}-{side}.jpg', self.data[side], 'image/jpeg') for side in ('left', 'right')}


def start_session(browser, name: str) -> dict:
    smoke.expect(browser.send('POST', '/v1/auth/guest'), 200, 'starting a guest session')
    return smoke.expect(browser.send('POST', '/v1/profiles', json_body={'name': name, 'owner': 'self', 'consent': True}), 201, 'making a profile').json()


def end_session(browser) -> None:
    browser.send('DELETE', '/v1/account/data')
    browser.send('POST', '/v1/auth/signout')


def finished(events: list) -> dict:
    names = [n for n, _, _ in events]
    assert names and names[-1] == 'reading' and 'error' not in names, f'the reading did not finish: it ended with {names[-3:]}'
    return events[-1][1]


def drill_page_closed(base: str, photos: Photos) -> tuple[str, str]:
    """A person closes the page in the middle of a reading: the app must stop, keep nothing, and carry on for everyone else."""
    browser = smoke.Browser(base)
    profile = start_session(browser, 'Closed Page')
    try:
        body, kind = smoke.multipart({'profileId': profile['id'], **photos.fields}, photos.files('closed'))
        request = urllib.request.Request(base + '/v1/readings', data=body, method='POST', headers={'Content-Type': kind})
        reply = browser.opener.open(request, timeout=120)
        for raw in reply:  # wait for the first step to be announced, then walk away
            if raw.startswith(b'event: stage'):
                break
        reply.close()
        end = time.monotonic() + CLOSED_PAGE_WAIT
        while time.monotonic() < end:
            time.sleep(2)
            assert smoke.kiro_at(base), 'the app stopped answering after a page was closed in the middle of a reading'
            saved = browser.get(f'/v1/readings?profileId={profile["id"]}').json()
            assert saved == [], 'a reading that nobody waited for was saved'
        shown = browser.get('/v1/profiles').json()
        assert shown and shown[0]['readingCount'] == 0, 'the profile counts a reading that was never finished'
        return 'PASS', f'nothing was saved after {CLOSED_PAGE_WAIT:.0f} s, and the app went on answering'
    finally:
        end_session(browser)


def drill_two_browsers(base: str, photos: Photos) -> tuple[str, str]:
    """Two people read at the same time, each in their own browser: both finish, and neither sees the other's reading."""
    outcomes: dict[str, object] = {}
    started = time.monotonic()

    def person(label: str) -> None:
        browser = smoke.Browser(base)
        try:
            profile = start_session(browser, f'Browser {label}')
            status, events = browser.stream('/v1/readings', {'profileId': profile['id'], **photos.fields}, photos.files(label))
            assert status == 200, f'the reading answered {status}'
            reading = finished(events)
            mine = browser.get('/v1/readings').json()
            assert [r['id'] for r in mine] == [reading['id']], 'the list of readings is not exactly this browser\'s one reading'
            outcomes[label] = reading['id']
        except Exception as exc:  # noqa: BLE001 (shown below)
            outcomes[label] = exc
        finally:
            end_session(browser)

    threads = [threading.Thread(target=person, args=(label,)) for label in ('one', 'two')]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(300)
    errors = [f'{label}: {v}' for label, v in outcomes.items() if isinstance(v, Exception)]
    assert not errors and len(outcomes) == 2, f'a browser failed while another was reading: {errors or "no answer in 300 s"}'
    assert outcomes['one'] != outcomes['two'], 'two browsers were given the same reading'
    return 'PASS', f'both readings finished in {time.monotonic() - started:.0f} s, each in its own browser'


def another_tab(browser):
    """A second tab of the same browser: its own connection, the same cookies (so the same session)."""
    tab = smoke.Browser(browser.base)
    for cookie in browser.jar:
        tab.jar.set_cookie(cookie)
    return tab


def drill_two_tabs(base: str, photos: Photos) -> tuple[str, str]:
    """One person has the website open in two tabs: one session, two connections. Both tabs read at the same moment, both readings
    are kept, and a chat started in one tab about the other tab's reading works. Then one tab ends the session while the other is in
    the middle of a reading: that reading must end with an error and nothing saved."""
    tab_one = smoke.Browser(base)
    first = start_session(tab_one, 'Tab One')
    second = smoke.expect(tab_one.send('POST', '/v1/profiles', json_body={'name': 'Tab Two', 'owner': 'self', 'consent': True}), 201, 'making a second profile').json()
    tab_two = another_tab(tab_one)
    try:
        started = time.monotonic()
        outcomes: dict[str, object] = {}

        def read(label: str, tab, profile: dict) -> None:
            try:
                status, events = tab.stream('/v1/readings', {'profileId': profile['id'], **photos.fields}, photos.files(label))
                assert status == 200, f'the reading answered {status}'
                outcomes[label] = finished(events)
            except Exception as exc:  # noqa: BLE001 (shown below)
                outcomes[label] = exc

        threads = [threading.Thread(target=read, args=('one', tab_one, first)), threading.Thread(target=read, args=('two', tab_two, second))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(300)
        errors = [f'{label}: {v}' for label, v in outcomes.items() if isinstance(v, Exception)]
        assert not errors and len(outcomes) == 2, f'a tab failed while the other was reading: {errors or "no answer in 300 s"}'
        one, two = outcomes['one'], outcomes['two']
        assert one['id'] != two['id'] and {one['profileId'], two['profileId']} == {first['id'], second['id']}, 'the two tabs were not given one reading each'  # type: ignore[index]
        for label, tab in (('first', tab_one), ('second', tab_two)):
            seen = {r['id'] for r in tab.get('/v1/readings').json()}
            assert seen == {one['id'], two['id']}, f'the {label} tab does not see both readings'  # type: ignore[index]
        counts = {p['name']: p['readingCount'] for p in tab_two.get('/v1/profiles').json()}
        assert counts == {'Tab One': 1, 'Tab Two': 1}, f'the profiles count their readings as {counts}'

        # a chat started in one tab about the reading made in the other
        convo = smoke.expect(tab_two.send('POST', f'/v1/readings/{one["id"]}/conversations'), 201, 'starting a chat in the second tab').json()  # type: ignore[index]
        question = {'text': 'What does my heart line say?'}
        answer = smoke.expect(tab_two.send('POST', f'/v1/conversations/{convo["id"]}/messages', json_body=question), 200, 'a chat message in the second tab').json()['assistant']
        assert answer['text'], 'the chat answered with nothing'
        chats = tab_one.get(f'/v1/conversations?readingId={one["id"]}').json()  # type: ignore[index]
        assert [c['id'] for c in chats] == [convo['id']] and chats[0]['messageCount'] == 2, 'the first tab does not see the chat that the second tab started'

        # the second tab ends the session while the first is in the middle of a reading
        ended: list[int] = []

        def end_it_once(name: str, _data) -> None:
            if name == 'stage' and not ended:
                ended.append(tab_two.send('POST', '/v1/auth/signout').status)

        status, events = tab_one.stream('/v1/readings', {'profileId': first['id'], **photos.fields}, photos.files('late'), on_event=end_it_once)
        names = [n for n, _, _ in events]
        assert status == 200 and ended == [204], f'the second tab could not end the session (the reading answered {status}; the sign-out was answered {ended})'
        assert 'reading' not in names and names[-1] == 'error' and events[-1][1]['code'] == 'expired', f'a reading went on after the session was ended in another tab: it finished with {names[-3:]}'
        assert tab_one.get('/v1/profiles').status == 410, 'the first tab was not told that the session had ended'
        return 'PASS', f'two tabs read at once and both readings were kept ({time.monotonic() - started:.0f} s); a session ended in one tab stopped the other tab\'s reading, with nothing saved'
    finally:
        end_session(tab_one)
        end_session(tab_two)


def drill_bad_photos(base: str, bad: list[Path]) -> tuple[str, str]:
    """Each photo meant to fail goes to the photo checks, as a person's would. The answer is shown, so the report can quote it."""
    if not bad:
        return 'WARN', 'no photo meant to fail was found (see the photo check above)'
    browser = smoke.Browser(base)
    start_session(browser, 'Bad Photos')
    try:
        said = []
        accepted = []
        for path in bad:
            files = {'photo': (path.name, path.read_bytes(), 'image/png' if path.suffix.lower() == '.png' else 'image/jpeg')}
            reply = browser.send('POST', '/v1/photos/validate', fields={'side': 'left'}, files=files)
            assert reply.status in (200, 422), f'{path.name}: the photo check answered {reply.status}'
            if reply.status == 422:
                said.append(f'{path.name}: refused before it was read ({reply.error_code()})')
                continue
            verdict = reply.json()
            problems = [c for c in verdict['checks'] if c['status'] in ('fail', 'warn')]
            if verdict['ok'] and not problems:
                accepted.append(path.name)
            said.append(f'{path.name}: {"refused" if not verdict["ok"] else "accepted with a warning"}: ' + '; '.join(f'{c["status"]} {c["id"]}' for c in problems))
        if accepted:
            return 'WARN', f'{", ".join(accepted)} passed every check without a warning. Is it really a bad photo? ' + ' | '.join(said)
        return 'PASS', ' | '.join(said)
    finally:
        end_session(browser)


def drill_google_down_one_reading(base: str, photos: Photos) -> tuple[str, str]:
    """The app was told that Google lives at a closed port. A real reading must still finish, with the fixed wording and a plain
    note, and the chat must still answer. This is what a Google outage looks like to a person."""
    browser = smoke.Browser(base)
    profile = start_session(browser, 'Google Down')
    try:
        assert browser.get('/v1/health').json().get('writer') == 'gemini', 'this copy of the app did not believe it had a Gemini key'
        started = time.monotonic()
        status, events = browser.stream('/v1/readings', {'profileId': profile['id']}, photos.files('down'))
        assert status == 200, f'the reading answered {status}'
        reading = finished(events)
        meta = reading['meta']
        assert meta['provider'] == 'knowledge-base', f'the report says it was written by {meta["provider"]!r} though Google could not be reached'
        assert meta.get('note') and 'Gemini' in meta['note'], f'the reading does not say why Gemini was not used: {meta.get("note")!r}'
        assert len(reading['report']['themes']) == 5 and reading['report']['uncertainty'], 'the fixed-wording report is incomplete'
        convo = smoke.expect(browser.send('POST', f'/v1/readings/{reading["id"]}/conversations'), 201, 'starting a chat').json()
        answer = smoke.expect(browser.send('POST', f'/v1/conversations/{convo["id"]}/messages', json_body={'text': 'What does my heart line say?'}), 200, 'a chat message').json()['assistant']
        assert answer['text'] and answer.get('source') == 'knowledge-base' and answer.get('note'), f'the chat answer was not an honest fallback: {answer.get("source")}, {answer.get("note")!r}'
        return 'PASS', f'the reading finished in {time.monotonic() - started:.0f} s with the fixed wording; it said: "{meta["note"]}"'
    finally:
        end_session(browser)


# ------------------------------------------------------------------ the privacy audit


def snapshot(root: Path) -> dict[str, tuple[int, int]]:
    """Every file under `root` as {name: (size, modified)}, leaving out other people's code and caches."""
    seen = {}
    for directory, names, files in os.walk(root):
        names[:] = [n for n in names if n not in AUDIT_SKIP]
        for name in files:
            path = Path(directory) / name
            try:
                info = path.stat()
            except OSError:
                continue
            seen[path.relative_to(root).as_posix()] = (info.st_size, info.st_mtime_ns)
    return seen


def changed_files(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> list[str]:
    return sorted(name for name, state in after.items() if before.get(name) != state)


def leaks_in(blob: bytes, markers: list[str]) -> list[str]:
    """What in this text or file must not be there: one of the markers (a name, a file name, an e-mail address that only this audit
    knows), or the start of a picture."""
    found = []
    lowered = blob.lower()
    for marker in markers:
        if marker.lower().encode() in lowered:
            found.append(f'"{marker}"')
    for sign in IMAGE_SIGNS:
        if sign in blob:
            found.append(f'picture data ({sign[:6]!r})')
    return found


def audit_photos_through(base: str, photos: Photos, markers: dict[str, str]) -> None:
    """Sends photos that have a file name no one else knows, a person's name and an e-mail address through the whole app."""
    browser = smoke.Browser(base)
    profile = start_session(browser, markers['name'])
    try:
        status, events = browser.stream('/v1/readings', {'profileId': profile['id'], **photos.fields}, photos.files(markers['file']))
        assert status == 200, f'the audit reading answered {status}'
        reading = finished(events)
        convo = smoke.expect(browser.send('POST', f'/v1/readings/{reading["id"]}/conversations'), 201, 'starting a chat').json()
        question = f'My name is {markers["name"]} and my e-mail is {markers["email"]}. What does my head line say?'
        smoke.expect(browser.send('POST', f'/v1/conversations/{convo["id"]}/messages', json_body={'text': question}), 200, 'a chat message')
        smoke.expect(browser.get('/v1/account/export'), 200, 'the data download')
    finally:
        end_session(browser)


def audit_flow(base: str, photos: Photos, markers: dict[str, str]) -> tuple[str, str]:
    audit_photos_through(base, photos, markers)
    return 'PASS', 'a reading, a chat message and the data download'


def audit_result(apps: list[RunningApp], markers: dict[str, str], before: dict[str, tuple[int, int]], root: Path = ROOT) -> tuple[str, str]:
    """Run after the apps have stopped: their logs, their private temporary folders and the project folder must hold nothing of
    what went through (a picture, a file name, a name, an e-mail address)."""
    watch = [markers['name'], markers['file'], markers['email'], markers['token']]
    problems = []
    lines = 0
    harmless = []
    for app in apps:
        log = app.log_bytes()
        lines += len(log.splitlines())
        for leak in leaks_in(log, watch):
            problems.append(f'the log contains {leak}')
        for path in [p for p in sorted(app.tmp.rglob('*')) if p.is_file()]:
            content = path.read_bytes()
            found = leaks_in(content, watch)
            if found or len(content) > 200_000:
                problems.append(f'the private temporary folder holds {path.name} ({len(content):,} bytes{", with " + ", ".join(found) if found else ""})')
            else:
                harmless.append(path.name)
    for name in changed_files(before, snapshot(root)):
        problems.append(f'the project folder has a new or changed file: {name}')
        content = (root / name).read_bytes() if (root / name).is_file() else b''
        for leak in leaks_in(content, watch):
            problems.append(f'  and {name} contains {leak}')
    if problems:
        return 'FAIL', '; '.join(problems[:6])
    extra = f' ({len(harmless)} small temporary file(s) from the libraries, with no photo data in them)' if harmless else ''
    return 'PASS', f'no picture, file name, name or e-mail address in the log ({lines} lines), the private temporary folder{extra} or the project folder'


# ------------------------------------------------------------------ the whole run


def run_smoke(report: Report, app: RunningApp, folder: Path, real: bool) -> str:
    """The smoke check against the app that preflight started. Its lines are shown as they are, indented."""
    smoke.REAL_PHOTOS = folder
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        ok = smoke.run_checks(app.base, expect_real=real, expect_gemini=False)
    text = captured.getvalue()
    for line in text.splitlines():
        report.say(('    ' + line) if line.strip() else '')
    wrote = re.search(r'report by ([\w-]+)(?: \(([^)]*)\))?(?:, because: ([^;\]]*))?', text)
    detail = 'the smoke check passed' if ok else 'the smoke check failed (its lines are above)'
    report.counts['PASS' if ok else 'FAIL'] += 1
    report.say(f'  {"PASS" if ok else "FAIL"}  {detail}')
    if ok and wrote and wrote.group(1) == 'knowledge-base':
        report.counts['WARN'] += 1
        report.say('  WARN  Gemini did not write the report in this run' + (f': {wrote.group(3).strip()}' if wrote.group(3) else '') + ' (the app falls back to the fixed wording, as designed)')
    elif ok and wrote:
        report.say(f'          (the report of your own photos was written by {wrote.group(1)}{" " + wrote.group(2) if wrote.group(2) else ""})')
    return 'PASS' if ok else 'FAIL'


def make_markers() -> dict[str, str]:
    """Words that nobody else would write, to look for afterwards. Letters only: the app refuses a name with five digits in a row
    (it looks like a phone number), and a random hexadecimal token has them often enough to fail about one run in three."""
    token = ''.join(secrets.choice('bcdfghjkmnpqrstvwxz') for _ in range(10))
    return {'token': token, 'name': f'Audit Person {token}', 'file': f'audit-{token}', 'email': f'audit.{token}@example.com'}


def start_app(report: Report, app: RunningApp, name: str) -> bool:
    try:
        app.start()
        app.wait_until_up()
    except RuntimeError as exc:
        report.result('FAIL', name, str(exc).replace('\n', ' | '))
        return False
    report.result('PASS', name, f'{app.base}; its log is kept in a file so that it can be searched afterwards')
    return True


def run_app_checks(report: Report, args: argparse.Namespace, settings, model_ok: bool, pairs: list[tuple[str, Path, Path]], bad: list[Path]) -> None:
    photos = Photos((pairs[0][1], pairs[0][2]) if pairs and model_ok else None)
    keyed = bool(settings.gemini_api_key) and not args.no_gemini
    work = Path(tempfile.mkdtemp(prefix='kiro-preflight-'))
    markers = make_markers()
    before = snapshot(ROOT)
    started: list[RunningApp] = []
    report.group('The running app  (started by this check, on a spare port; your own window is not touched)')

    # 1. the app as you run it: the smoke check, then the privacy flow
    first = RunningApp(work / 'main', extra_env=None if keyed else {'GEMINI_API_KEY': ''})
    started.append(first)
    try:
        if not start_app(report, first, 'the app starts'):
            return
        report.say()
        report.say('  The smoke check (about a minute; with your photos it makes a real reading):')
        run_smoke(report, first, args.photos, photos.real)
        report.say()
        report.step('photos, a file name, a name and an e-mail address go through the whole app', lambda: audit_flow(first.base, photos, markers))
    finally:
        first.stop()

    # 2. a second copy that thinks Google is at a closed port: the drills. Nothing here asks Gemini for anything.
    second = RunningApp(work / 'google-down', extra_env={'GEMINI_API_KEY': 'preflight-drill-not-a-real-key', 'GOOGLE_GEMINI_BASE_URL': 'http://127.0.0.1:9'})
    started.append(second)
    report.say()
    try:
        if start_app(report, second, 'a second copy starts, told that Google is unreachable'):
            report.step('your photos meant to fail get the answer a person would see', lambda: drill_bad_photos(second.base, bad))
            report.step('a page closed in the middle of a reading leaves nothing behind', lambda: drill_page_closed(second.base, photos))
            report.step('two browsers reading at the same time both finish, and stay apart', lambda: drill_two_browsers(second.base, photos))
            report.step('two tabs of one session: both readings are kept, and a session ended in one tab stops the other reading', lambda: drill_two_tabs(second.base, photos))
            if photos.real:
                report.step('Google unreachable: a real reading still finishes, with the fixed wording and a plain note', lambda: drill_google_down_one_reading(second.base, photos))
            else:
                report.result('WARN', 'Google unreachable: a real reading still finishes, with the fixed wording and a plain note', 'not run: it needs the hand model and a pair of your photos')
    finally:
        second.stop()

    report.step('privacy audit: nothing of that is left in the logs, the temporary folders or the project folder', lambda: audit_result(started, markers, before))
    shutil.rmtree(work, ignore_errors=True)


def save_copy(report: Report, folder: Path) -> Path | None:
    target = folder / 'preflight.txt'
    try:
        folder.mkdir(parents=True, exist_ok=True)
        target.write_text(report.text(), encoding='utf-8')
    except OSError as exc:
        print(f'     (A text copy could not be saved in {folder}: {exc.strerror or type(exc).__name__}.)')
        return None
    return target


def run(args: argparse.Namespace, report: Report) -> int:
    from app.core.config import read_settings

    settings = read_settings()
    report.say(f'Kiro AI preflight   {datetime.now().strftime("%Y-%m-%d %H:%M")}')

    report.group('This computer')
    report.step('Python', check_python)
    report.step('every package is the version the tests used', check_packages)
    report.step('one OpenCV package', check_opencv)
    model_ok = report.step('the hand model', lambda: check_model(settings.hand_model)) == 'PASS'
    report.step('settings', lambda: check_settings(settings))

    report.group('The project')
    report.step('the website', check_site)
    for what, problems in repo_checks.all_checks(ROOT):
        report.step(what, lambda problems=problems: ('FAIL', '; '.join(problems[:4])) if problems else ('PASS', ''))
    pairs, bad = find_pairs(args.photos)
    report.step(f'your photos in {args.photos}', lambda: check_photos(args.photos))

    report.group('Google')
    if args.no_gemini:
        report.result('WARN', 'one small request to Gemini', 'skipped (--no-gemini)')
    elif not settings.gemini_api_key:
        report.result('WARN', 'one small request to Gemini', 'skipped: there is no key')
    else:
        report.step('one small request to Gemini', lambda: check_google(settings, report))

    if args.no_server:
        report.group('The running app')
        report.result('WARN', 'the app was not started', '--no-server')
    else:
        run_app_checks(report, args, settings, model_ok, pairs, bad)

    c = report.counts
    report.say()
    report.say(f'{c["PASS"]} passed, {c["WARN"]} warning(s), {c["FAIL"]} failed.')
    if c['FAIL']:
        report.say('Fix the FAIL lines first; each says what to do.')
    elif c['WARN']:
        report.say('Nothing is broken. Read the WARN lines: each is something to know or to do.')
    report.say()
    report.say('RESULT: PASS' if not c['FAIL'] else 'RESULT: FAIL')
    return 1 if c['FAIL'] else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description='Checks that everything is in place for a demonstration.')
    parser.add_argument('--no-gemini', action='store_true', help='do not make the one small request to Google')
    parser.add_argument('--no-server', action='store_true', help='only look at the files and settings')
    parser.add_argument('--photos', type=Path, default=TEST_PHOTOS, help='the folder with your photos (default: ..\\test-photos)')
    parser.add_argument('--out', type=Path, default=DEBUG, help='where the text copy goes (default: ..\\debug)')
    args = parser.parse_args(argv)

    report = Report()
    try:
        code = run(args, report)
    finally:
        saved = save_copy(report, args.out)
    if saved is not None:
        print(f'A text copy of this is saved in {saved}')
        print()
    return code


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print('\nStopped.')
        sys.exit(1)
