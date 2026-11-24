"""scripts/preflight.py, the one command that checks everything before a demonstration. Most of it is looked at here in small pieces; the
parts that start the app as its own process are run for real by `run.bat preflight` and `run.bat fresh`. The drills that talk to the app run here against
the real app, listening on a real port inside this process."""

from __future__ import annotations

import importlib.util
import socket
import sys
import threading
import time
import types
from pathlib import Path

import pytest
import uvicorn
from fake_firebase import PROJECT, private_key_text, write_key_file
from fake_gemini import FakeModel, service_for, unavailable

from app.core.config import Settings
from app.main import create_app

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
KEY = 'AIzaSyTestKeyForThePreflightOnly0123456789'


@pytest.fixture(scope='module')
def pf():
    spec = importlib.util.spec_from_file_location('preflight_under_test', SCRIPTS / 'preflight.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules['preflight_under_test'] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop('preflight_under_test', None)


def listening(app) -> tuple[uvicorn.Server, threading.Thread, str]:
    probe = socket.socket()
    probe.bind(('127.0.0.1', 0))
    port = probe.getsockname()[1]
    probe.close()
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            return server, thread, f'http://127.0.0.1:{port}'
        time.sleep(0.05)
    raise AssertionError('the test server did not start')


@pytest.fixture
def live(site_dir):
    """The real app on a real port, as the drills see it. Photos marked as samples; no pause between the steps."""
    server, thread, base = listening(create_app(Settings(env='test', site_dir=site_dir, stage_pause_ms=0)))
    yield base
    server.should_exit = True
    thread.join(10)


@pytest.fixture
def live_slow(site_dir):
    """The same, with a pause between the steps, so that a reading is still going on when a page is closed."""
    server, thread, base = listening(create_app(Settings(env='test', site_dir=site_dir, stage_pause_ms=300)))
    yield base
    server.should_exit = True
    thread.join(10)


# ------------------------------------------------------------------ what is printed


def test_a_line_per_check_with_its_note_and_the_counts(pf, capsys):
    report = pf.Report()
    report.result('PASS', 'Python', 'Python 3.14.5')
    report.result('WARN', 'photos', 'only one pair')
    report.result('FAIL', 'x' * 60, 'y' * 60)
    out = capsys.readouterr().out
    assert report.counts == {'PASS': 1, 'WARN': 1, 'FAIL': 1}
    assert '  PASS  Python   [Python 3.14.5]' in out and '  WARN  photos   [only one pair]' in out
    assert max(len(line) for line in out.splitlines()) <= 105  # a long note goes on its own, wrapped lines
    assert report.text() == out


def test_a_check_that_crashes_is_a_failure_and_the_others_still_run(pf, capsys):
    report = pf.Report()

    def broken():
        raise ValueError('boom')

    assert report.step('one', broken) == 'FAIL'
    assert report.step('two', lambda: ('PASS', 'fine')) == 'PASS'
    out = capsys.readouterr().out
    assert 'the check itself broke: ValueError: boom' in out and report.counts['FAIL'] == 1 and report.counts['PASS'] == 1


# ------------------------------------------------------------------ this computer


def test_this_python_is_good_enough(pf):
    status, note = pf.check_python()
    assert status == 'PASS' and '64-bit' in note


def test_every_pinned_package_must_be_there_at_that_version(pf, tmp_path):
    from importlib import metadata

    have = metadata.version('pytest')
    ok = tmp_path / 'ok.txt'
    ok.write_text(f'pytest=={have}\n# a comment\n')
    assert pf.check_packages(ok) == ('PASS', '1 of 1 packages are installed at the version the tests used')
    bad = tmp_path / 'bad.txt'
    bad.write_text('pytest==0.0.1\nno-such-package-anywhere==1.0\n')
    status, note = pf.check_packages(bad)
    assert status == 'FAIL' and 'no-such-package-anywhere is not installed' in note and f'pytest {have} (wanted 0.0.1)' in note and 'run.bat installs them' in note


def test_one_opencv_package_only(pf):
    status, note = pf.check_opencv()
    assert status in ('PASS', 'WARN') and 'OpenCV' in note


def test_a_missing_hand_model_is_a_warning_and_a_damaged_one_a_failure(pf, tmp_path):
    status, note = pf.check_model(tmp_path / 'hand_landmarker.task')
    assert status == 'WARN' and 'SAMPLE reading' in note and 'run.bat models' in note
    damaged = tmp_path / 'hand_landmarker.task'
    damaged.write_bytes(b'not a model' * 100)
    status, note = pf.check_model(damaged)
    assert status == 'FAIL' and 'damaged' in note


def test_the_key_is_said_to_be_present_and_never_shown(pf, tmp_path):
    present = Settings(gemini_api_key=KEY, gemini_model='gemini-test')
    status, note = pf.check_settings(present, tmp_path / '.env')
    assert status == 'PASS' and 'present' in note and 'gemini-test' in note and KEY not in note and 'AIza' not in note
    status, note = pf.check_settings(Settings(), tmp_path / '.env')
    assert status == 'WARN' and 'no Gemini key' in note and 'works fully without one' in note


def test_the_settings_check_says_where_accounts_are_kept(pf, tmp_path):
    key = tmp_path / 'firebase-service-account.json'
    assert pf.storage_check(Settings(storage='memory', firebase_key=key)) == ('PASS', 'accounts are kept in memory only (STORAGE=memory)')
    status, words = pf.storage_check(Settings(storage='auto', firebase_key=key))
    assert status == 'PASS' and 'memory only (no Firebase key' in words
    write_key_file(key)
    status, words = pf.storage_check(Settings(storage='auto', firebase_key=key))
    assert status == 'PASS' and f'online database, Firebase project {PROJECT}' in words and 'run.bat firebase' in words
    assert private_key_text() not in words
    status, note = pf.check_settings(Settings(storage='auto', firebase_key=key), tmp_path / '.env')
    assert status == 'WARN' and 'Accounts are kept in the online database' in note  # WARN only because there is no Gemini key


def test_a_firebase_key_given_in_the_setting_counts_as_a_key(pf, tmp_path):
    from fake_firebase import key_text

    no_file = tmp_path / 'firebase-service-account.json'
    status, words = pf.storage_check(Settings(storage='firestore', firebase_key=no_file, firebase_key_json=key_text()))
    assert status == 'PASS' and f'online database, Firebase project {PROJECT}' in words and private_key_text() not in words
    status, words = pf.storage_check(Settings(storage='firestore', firebase_key=no_file, firebase_key_json='{"type": "x"}'))
    assert status == 'FAIL' and 'FIREBASE_KEY_JSON is not a service account key' in words


def test_a_firebase_key_the_server_cannot_use_is_a_warning_or_a_failure(pf, tmp_path):
    key = tmp_path / 'firebase-service-account.json'
    status, note = pf.check_settings(Settings(storage='firestore', firebase_key=key, gemini_api_key=KEY), tmp_path / '.env')
    assert status == 'FAIL' and 'STORAGE=firestore, but there is no Firebase key' in note and 'run.bat would stop' in note
    write_key_file(key, private_key='cut short')
    status, words = pf.storage_check(Settings(storage='auto', firebase_key=key))
    assert status == 'WARN' and 'cannot be read' in words and 'kept in memory only' in words
    status, words = pf.storage_check(Settings(storage='firestore', firebase_key=key))
    assert status == 'FAIL' and 'run.bat would stop' in words


# ------------------------------------------------------------------ the project


def test_the_website_check_tells_a_sample_build_from_the_real_one(pf, tmp_path):
    site = tmp_path / 'dist-server'
    site.mkdir()
    assert pf.check_site(site)[0] in ('WARN', 'FAIL')  # nothing built yet
    (site / 'index.html').write_text('<html></html>')
    status, note = pf.check_site(site)
    assert status == 'FAIL' and 'sample-data build' in note
    (site / 'build-info.json').write_text('{"mock": true, "mode": "production"}')
    assert pf.check_site(site)[0] == 'FAIL'
    (site / 'build-info.json').write_text('{"mock": false, "mode": "server"}')
    status, note = pf.check_site(site)
    assert status == 'PASS' and 'built from these sources' in note


def put(folder: Path, *names: str) -> None:
    for name in names:
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x')


def test_pairs_are_found_by_the_words_left_and_right_in_any_folder(pf, tmp_path):
    put(tmp_path, 'person1/left.jpg', 'person1/right.jpg', 'maria/IMG_left_hand.JPG', 'maria/IMG_right_hand.JPG', 'solo/left.jpg', 'notes.txt')
    pairs, bad = pf.find_pairs(tmp_path)
    assert [name for name, _, _ in pairs] == ['maria', 'person1'] and bad == []
    assert pairs[1][1].name == 'left.jpg' and pairs[1][2].name == 'right.jpg'


def test_a_photo_with_bad_or_blur_in_its_name_is_meant_to_fail_and_is_not_a_pair(pf, tmp_path):
    put(tmp_path, 'person1/left.jpg', 'person1/right.jpg', 'bad_blurry.jpg', 'dark/left.png', 'dark/right.png', 'not-palm.jpeg', 'person2/left_blur.jpg', 'person2/right.jpg')
    pairs, bad = pf.find_pairs(tmp_path)
    assert [name for name, _, _ in pairs] == ['person1']
    assert sorted(p.name for p in bad) == ['bad_blurry.jpg', 'left.png', 'left_blur.jpg', 'not-palm.jpeg', 'right.png']


def test_the_photo_check_says_what_is_still_needed(pf, tmp_path):
    status, note = pf.check_photos(tmp_path / 'missing')
    assert status == 'WARN' and 'does not exist' in note
    put(tmp_path, 'person1/left.jpg', 'person1/right.jpg')
    status, note = pf.check_photos(tmp_path)
    assert status == 'WARN' and '1 pair(s) (person1), 0 photo(s) meant to fail' in note and '2 more pair(s)' in note and 'a photo that should fail' in note
    put(tmp_path, 'p2/left.jpg', 'p2/right.jpg', 'p3/left.jpg', 'p3/right.jpg', 'bad1.jpg')
    status, note = pf.check_photos(tmp_path)
    assert status == 'PASS' and '3 pair(s)' in note and '1 photo(s) meant to fail' in note


def test_google_answering_is_a_pass_and_a_temporary_trouble_only_a_warning(pf, monkeypatch):
    settings = Settings(gemini_api_key=KEY, gemini_model='fake-gemini')
    working = service_for(FakeModel(lambda prompt: {'reply': 'ready'}))
    monkeypatch.setattr('app.llm.gemini.service_from_settings', lambda s: working)
    status, note = pf.check_google(settings, pf.Report())
    assert status == 'PASS' and 'answered' in note and KEY not in note

    for kind, expected in (('overloaded', 'WARN'), ('rate_limited', 'WARN'), ('timeout', 'WARN'), ('bad_key', 'FAIL'), ('bad_model', 'FAIL'), ('region', 'FAIL')):
        failing = service_for(FakeModel(lambda prompt, kind=kind: (_ for _ in ()).throw(unavailable(kind, f'detail {KEY}'))))
        monkeypatch.setattr('app.llm.gemini.service_from_settings', lambda s, failing=failing: failing)
        status, note = pf.check_google(settings, pf.Report())
        assert status == expected, kind
        assert f'[{kind}]' in note and KEY not in note
        if expected == 'WARN':
            assert 'fixed wording' in note  # the app keeps working


# ------------------------------------------------------------------ the app, as its own process


def test_the_app_is_started_with_a_private_temporary_folder_and_its_log_in_a_file(pf, tmp_path, monkeypatch):
    monkeypatch.setattr(pf, 'free_port', lambda start=0: 8801)
    app = pf.RunningApp(tmp_path / 'one', extra_env={'GEMINI_API_KEY': '', 'EXTRA': 'yes'})
    assert app.base == 'http://127.0.0.1:8801' and app.tmp.is_dir() and app.tmp.parent == tmp_path / 'one'
    for name in ('TMP', 'TEMP', 'TMPDIR'):
        assert app.env[name] == str(app.tmp)
    assert app.env[pf.serve.CHILD_FLAG] == '1' and app.env['PYTHONUTF8'] == '1'
    assert app.env['GEMINI_API_KEY'] == '' and app.env['EXTRA'] == 'yes'  # a blank one wins over backend\.env, as it should


def test_an_app_that_stops_while_starting_is_reported_with_its_last_lines(pf, tmp_path, monkeypatch):
    broken = tmp_path / 'serve.py'
    broken.write_text('import sys\nprint("boom: the model is missing")\nsys.exit(3)\n')
    monkeypatch.setattr(pf, 'SERVE', broken)
    app = pf.RunningApp(tmp_path / 'broken')
    app.start()
    with pytest.raises(RuntimeError) as why:
        app.wait_until_up(timeout=20)
    app.stop()
    assert 'code 3' in str(why.value) and 'boom: the model is missing' in str(why.value)


def test_the_app_is_stopped_with_everything_it_started(pf, monkeypatch):
    """On Windows the Python of a private environment is a launcher that starts the real one: ending only the launcher would leave
    the server running, with its port and its log file."""
    import subprocess

    ran = []
    monkeypatch.setattr(subprocess, 'run', lambda cmd, **kw: ran.append(cmd))
    process = types.SimpleNamespace(pid=4242, wait=lambda timeout=None: 0, terminate=lambda: pytest.fail('a hard stop of the launcher alone'))
    pf.stop_tree(process, windows=True)
    assert ran == [['taskkill', '/PID', '4242', '/T', '/F']]


def test_a_running_app_is_stopped_politely_first_and_by_force_if_it_will_not_go(pf):
    import subprocess

    polite = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    pf.stop_tree(polite, windows=False)
    assert polite.poll() is not None

    stubborn = subprocess.Popen(
        [sys.executable, '-c', 'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print("ready", flush=True); time.sleep(60)'],
        stdout=subprocess.PIPE, text=True,
    )
    assert stubborn.stdout.readline().strip() == 'ready'  # the handler is in place before it is asked to stop
    real_wait = stubborn.wait

    def impatient(timeout=None):  # the first wait (after terminate) gives up at once; the second one (after kill) is real
        if timeout == 20:
            raise subprocess.TimeoutExpired('x', timeout)
        return real_wait(timeout)

    stubborn.wait = impatient
    pf.stop_tree(stubborn, windows=False)
    assert stubborn.poll() is not None
    stubborn.stdout.close()


# ------------------------------------------------------------------ the drills, against the real app


def test_a_bad_photo_is_shown_the_answer_a_person_would_get(pf, live, tmp_path):
    from smoke import tiny_png

    grey = tmp_path / 'bad_grey.png'
    grey.write_bytes(tiny_png())
    status, note = pf.drill_bad_photos(live, [grey])
    assert status == 'PASS' and 'bad_grey.png: refused' in note and 'palm_visible' in note
    status, note = pf.drill_bad_photos(live, [])
    assert status == 'WARN' and 'no photo meant to fail' in note


def test_two_browsers_reading_at_once_both_finish_and_stay_apart(pf, live):
    status, note = pf.drill_two_browsers(live, pf.Photos(None))
    assert status == 'PASS' and 'each in its own browser' in note


def test_two_tabs_of_one_session_both_read_and_a_session_ended_in_one_stops_the_other(pf, live_slow):
    status, note = pf.drill_two_tabs(live_slow, pf.Photos(None))
    assert status == 'PASS' and 'two tabs read at once' in note and 'stopped the other tab' in note


def test_the_two_tabs_drill_catches_an_app_that_saves_a_reading_after_its_session_ended(pf, live_slow, monkeypatch):
    """A check that cannot fail is no check: an app that no longer notices an ended session must fail the drill."""
    from app.api import readings

    monkeypatch.setattr(readings, 'still_alive', lambda store, caller: True)
    with pytest.raises(AssertionError, match='a reading went on after the session was ended in another tab'):
        pf.drill_two_tabs(live_slow, pf.Photos(None))


def test_the_two_tabs_drill_catches_a_tab_that_cannot_see_the_other_tabs_reading(pf, live_slow, monkeypatch):
    """The same for the other half: if the readings of one session were kept apart per connection, the second tab would see only its own."""
    real = pf.another_tab

    def blind_tab(browser):
        tab = real(browser)
        send = tab.send

        def only_mine(method, path, *args, **kwargs):
            reply = send(method, path, *args, **kwargs)
            if method == 'GET' and path == '/v1/readings':
                reply.body = b'[]'
            return reply

        tab.send = only_mine
        tab.get = lambda path: only_mine('GET', path)
        return tab

    monkeypatch.setattr(pf, 'another_tab', blind_tab)
    with pytest.raises(AssertionError, match='does not see both readings'):
        pf.drill_two_tabs(live_slow, pf.Photos(None))


def test_a_page_closed_in_the_middle_of_a_reading_leaves_nothing_behind(pf, live_slow, monkeypatch):
    monkeypatch.setattr(pf, 'CLOSED_PAGE_WAIT', 3.0)
    status, note = pf.drill_page_closed(live_slow, pf.Photos(None))
    assert status == 'PASS' and 'nothing was saved' in note


def test_the_page_closed_drill_catches_an_app_that_keeps_working_and_saves(pf, live_slow, monkeypatch):
    """A check that cannot fail is no check: give the drill an app that goes on after the browser has left, and it must say so."""
    import asyncio

    from app.api import readings

    real = readings.stream_reading

    async def stubborn(**kwargs):
        chunks: asyncio.Queue = asyncio.Queue()

        async def drain():  # not tied to the request: it is not stopped when the browser goes
            async for chunk in real(**kwargs):
                await chunks.put(chunk)
            await chunks.put(None)

        asyncio.ensure_future(drain())
        while (chunk := await chunks.get()) is not None:
            yield chunk

    monkeypatch.setattr(readings, 'stream_reading', stubborn)
    monkeypatch.setattr(pf, 'CLOSED_PAGE_WAIT', 6.0)
    with pytest.raises(AssertionError, match='a reading that nobody waited for was saved'):
        pf.drill_page_closed(live_slow, pf.Photos(None))


def test_the_drills_use_a_real_pair_when_there_is_one_and_the_drawings_when_there_is_not(pf, tmp_path):
    left, right = tmp_path / 'left.jpg', tmp_path / 'right.jpg'
    left.write_bytes(b'L')
    right.write_bytes(b'R')
    real = pf.Photos((left, right))
    assert real.real and real.fields == {} and real.files('x')['left'] == ('x-left.jpg', b'L', 'image/jpeg')
    drawn = pf.Photos(None)
    assert not drawn.real and drawn.fields == {'leftSample': '1', 'rightSample': '1'} and len(drawn.data['left']) > 1000


# ------------------------------------------------------------------ the privacy audit


def test_the_made_up_name_and_address_are_always_ones_the_app_accepts(pf):
    """Found by running the zip on a clean copy: a random hexadecimal token sometimes held five digits in a row, which the app
    (rightly) takes for a phone number, so the privacy flow failed on about one run in three."""
    from app.validation import validate_email, validate_profile_name

    tokens = set()
    for _ in range(3000):
        made = pf.make_markers()
        assert validate_profile_name(made['name']) is None, made['name']
        assert validate_email(made['email']) is None, made['email']
        assert made['token'].isalpha() and made['token'].islower() and len(made['token']) == 10
        assert made['name'].endswith(made['token']) and made['token'] in made['file'] and made['token'] in made['email']
        tokens.add(made['token'])
    assert len(tokens) == 3000


MARKERS = {'token': 'abc123def4', 'name': 'Audit Person abc123def4', 'file': 'audit-abc123def4', 'email': 'audit.abc123def4@example.com'}


def fake_app(tmp_path: Path, log: bytes = b'INFO: started\nINFO: POST /v1/readings 200\n', temp_files: dict[str, bytes] | None = None):
    tmp = tmp_path / 'tmp'
    tmp.mkdir(parents=True, exist_ok=True)
    for name, content in (temp_files or {}).items():
        (tmp / name).write_bytes(content)
    return types.SimpleNamespace(tmp=tmp, log_bytes=lambda: log)


def project(tmp_path: Path) -> Path:
    root = tmp_path / 'project'
    (root / 'src').mkdir(parents=True)
    (root / 'src' / 'a.ts').write_text('export {}')
    (root / 'node_modules').mkdir()
    return root


def test_markers_and_pictures_are_found_wherever_they_are(pf):
    assert pf.leaks_in(b'ok ok ok', ['Audit Person']) == []
    assert pf.leaks_in(b'saved AUDIT PERSON abc', ['Audit Person']) == ['"Audit Person"']  # whatever the capitals
    assert any('picture data' in leak for leak in pf.leaks_in(b'x\xff\xd8\xff\xe0 more', []))
    assert any('picture data' in leak for leak in pf.leaks_in(b'<img src="data:image/jpeg;base64,/9j/4AAQ">', []))
    assert any('picture data' in leak for leak in pf.leaks_in(b'\x89PNG\r\n', []))


def test_a_new_or_changed_file_is_noticed_and_other_peoples_folders_are_not_looked_at(pf, tmp_path):
    root = project(tmp_path)
    before = pf.snapshot(root)
    assert set(before) == {'src/a.ts'}
    assert pf.changed_files(before, pf.snapshot(root)) == []
    (root / 'node_modules' / 'x.js').write_text('1')
    (root / 'src' / '__pycache__').mkdir()
    (root / 'src' / '__pycache__' / 'a.pyc').write_bytes(b'1')
    assert pf.changed_files(before, pf.snapshot(root)) == []
    (root / 'src' / 'a.ts').write_text('export const changed = 1')
    (root / 'dist-server').mkdir()
    (root / 'dist-server' / 'oops.jpg').write_bytes(b'\xff\xd8\xff')
    assert pf.changed_files(before, pf.snapshot(root)) == ['dist-server/oops.jpg', 'src/a.ts']


def test_an_audit_of_an_app_that_kept_nothing_passes(pf, tmp_path):
    root = project(tmp_path)
    status, note = pf.audit_result([fake_app(tmp_path)], MARKERS, pf.snapshot(root), root)
    assert status == 'PASS' and 'no picture, file name, name or e-mail address' in note and '2 lines' in note


@pytest.mark.parametrize(
    'log, expected',
    [
        (b'INFO: reading for Audit Person abc123def4\n', 'the log contains "Audit Person abc123def4"'),
        (b'INFO: got audit-abc123def4-left.jpg\n', 'the log contains "audit-abc123def4"'),
        (b'INFO: mail audit.abc123def4@example.com\n', 'audit.abc123def4@example.com'),
        (b'DEBUG: body \xff\xd8\xff\xe0\x00\x10JFIF\n', 'picture data'),
        (b'DEBUG: {"previews": "data:image/jpeg;base64,/9j/4AAQ"}\n', 'picture data'),
    ],
)
def test_a_leak_in_the_log_fails_the_audit(pf, tmp_path, log, expected):
    root = project(tmp_path)
    status, note = pf.audit_result([fake_app(tmp_path, log)], MARKERS, pf.snapshot(root), root)
    assert status == 'FAIL' and expected in note


def test_the_private_temporary_folder_must_hold_no_photo(pf, tmp_path):
    root = project(tmp_path)
    before = pf.snapshot(root)
    harmless = fake_app(tmp_path / 'a', temp_files={'tmpabc': b'12345'})
    status, note = pf.audit_result([harmless], MARKERS, before, root)
    assert status == 'PASS' and '1 small temporary file(s)' in note
    (tmp_path / 'b').mkdir()
    photo = fake_app(tmp_path / 'b', temp_files={'tmp1.bin': b'\xff\xd8\xff\xe0' + b'0' * 100})
    status, note = pf.audit_result([photo], MARKERS, before, root)
    assert status == 'FAIL' and 'tmp1.bin' in note and 'picture data' in note
    (tmp_path / 'c').mkdir()
    big = fake_app(tmp_path / 'c', temp_files={'raw.bin': b'0' * 300_000})
    status, note = pf.audit_result([big], MARKERS, before, root)
    assert status == 'FAIL' and 'raw.bin' in note and '300,000 bytes' in note


def test_a_file_the_app_left_in_the_project_folder_fails_the_audit(pf, tmp_path):
    root = project(tmp_path)
    before = pf.snapshot(root)
    (root / 'backend').mkdir()
    (root / 'backend' / 'last_photo.jpg').write_bytes(b'\xff\xd8\xff\xe0 audit-abc123def4')
    status, note = pf.audit_result([fake_app(tmp_path)], MARKERS, before, root)
    assert status == 'FAIL' and 'backend/last_photo.jpg' in note and 'contains' in note


def test_the_audit_looks_at_every_app_that_was_started(pf, tmp_path):
    root = project(tmp_path)
    clean = fake_app(tmp_path / 'one')
    leaky = fake_app(tmp_path / 'two', log=b'INFO: Audit Person abc123def4\n')
    status, note = pf.audit_result([clean, leaky], MARKERS, pf.snapshot(root), root)
    assert status == 'FAIL' and 'the log contains' in note


# ------------------------------------------------------------------ the whole run, without starting the app


@pytest.fixture
def quiet_computer(pf, monkeypatch):
    """Every check that depends on this computer (packages, the hand model, the website) answers as on a good one."""
    monkeypatch.setattr(pf, 'check_packages', lambda requirements=None: ('PASS', 'all there'))
    monkeypatch.setattr(pf, 'check_opencv', lambda: ('PASS', 'one'))
    monkeypatch.setattr(pf, 'check_model', lambda model: ('PASS', 'loads'))
    monkeypatch.setattr(pf, 'check_site', lambda site=None: ('PASS', 'built'))
    monkeypatch.setattr(pf.repo_checks, 'all_checks', lambda root=None: [('no keys', []), ('git ignores', [])])
    monkeypatch.setattr('app.core.config.read_settings', lambda: Settings())


def test_the_whole_run_without_the_app_saves_a_text_copy_and_passes(pf, quiet_computer, tmp_path, capsys):
    photos = tmp_path / 'test-photos'
    put(photos, 'person1/left.jpg', 'person1/right.jpg')
    code = pf.main(['--no-server', '--no-gemini', '--photos', str(photos), '--out', str(tmp_path / 'debug')])
    out = capsys.readouterr().out
    saved = (tmp_path / 'debug' / 'preflight.txt').read_text(encoding='utf-8')
    assert code == 0 and out.rstrip().endswith('preflight.txt') and 'RESULT: PASS' in out and 'RESULT: PASS' in saved
    assert 'the app was not started' in saved and 'Nothing is broken' in saved
    for heading in ('This computer', 'The project', 'Google'):
        assert heading in saved


def test_one_failed_check_makes_the_result_a_failure_and_says_so(pf, quiet_computer, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(pf.repo_checks, 'all_checks', lambda root=None: [('no keys', ['backend/x.ts:3: looks like a Google API key (AIza...)'])])
    code = pf.main(['--no-server', '--no-gemini', '--photos', str(tmp_path), '--out', str(tmp_path / 'debug')])
    out = capsys.readouterr().out
    assert code == 1 and 'RESULT: FAIL' in out and 'looks like a Google API key' in out and 'Fix the FAIL lines first' in out


def test_a_key_in_the_settings_is_asked_about_once_and_never_printed(pf, quiet_computer, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr('app.core.config.read_settings', lambda: Settings(gemini_api_key=KEY))
    service = service_for(FakeModel(lambda prompt: {'reply': 'ready'}))
    monkeypatch.setattr('app.llm.gemini.service_from_settings', lambda s: service)
    code = pf.main(['--no-server', '--photos', str(tmp_path), '--out', str(tmp_path / 'debug')])
    out = capsys.readouterr().out
    assert code == 0 and 'one small request to Gemini' in out and KEY not in out and 'AIza' not in out
    assert KEY not in (tmp_path / 'debug' / 'preflight.txt').read_text(encoding='utf-8')
    assert service.model.calls == 1


def test_the_smoke_lines_are_shown_and_a_fallback_to_the_fixed_wording_is_a_warning(pf, monkeypatch, tmp_path, capsys):
    def smoke_says(fell_back: bool):
        def run_checks(base, expect_real=False, expect_gemini=False):
            assert base == 'http://127.0.0.1:1' and expect_gemini is False
            print('\nKiro AI smoke check against ' + base + '\n')
            by = 'knowledge-base, because: Gemini is very busy right now' if fell_back else 'gemini (gemini-test)'
            print(f'  PASS  your own photos get a real reading   [report by {by}; chat answer by gemini]')
            print('\n17 of 17 checks passed.\n\nRESULT: PASS')
            return True

        return run_checks

    app = types.SimpleNamespace(base='http://127.0.0.1:1')
    monkeypatch.setattr(pf.smoke, 'run_checks', smoke_says(False))
    report = pf.Report()
    assert pf.run_smoke(report, app, tmp_path, real=True) == 'PASS'
    assert '17 of 17 checks passed' in report.text() and 'written by gemini gemini-test' in report.text() and report.counts == {'PASS': 1, 'WARN': 0, 'FAIL': 0}
    monkeypatch.setattr(pf.smoke, 'run_checks', smoke_says(True))
    report = pf.Report()
    assert pf.run_smoke(report, app, tmp_path, real=True) == 'PASS'
    assert report.counts == {'PASS': 1, 'WARN': 1, 'FAIL': 0} and 'Gemini is very busy right now' in report.text()
    monkeypatch.setattr(pf.smoke, 'run_checks', lambda base, expect_real=False, expect_gemini=False: False)
    report = pf.Report()
    assert pf.run_smoke(report, app, tmp_path, real=False) == 'FAIL' and report.counts['FAIL'] == 1
