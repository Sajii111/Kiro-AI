"""scripts/check_firebase.py, the check the person runs once their Firebase key is in backend/secrets. It runs here against a
database in a dictionary (fake_firebase.py): what matters is that it tells the truth about what worked, cleans up after itself,
never prints the private key, and says what to do when something fails."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from fake_firebase import PROJECT, FakeBackend, private_key_text, write_key_file

from app.core.config import Settings
from app.store.persist import StorageUnavailable

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'check_firebase.py'


@pytest.fixture(scope='module')
def check():
    spec = importlib.util.spec_from_file_location('check_firebase', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def key(tmp_path):
    return tmp_path / 'secrets' / 'firebase-service-account.json'


def never_called(_settings):
    raise AssertionError('the check went on to the database although the key could not be used')


def result_line(out: str) -> str:
    return [line for line in out.splitlines() if line.startswith('RESULT:')][-1]


def run(check, capsys, key, backend=None, **settings):
    code = check.main([], settings=Settings(storage=settings.pop('storage', 'auto'), firebase_key=key, **settings),
                      make_backend=(lambda _settings: backend) if backend is not None else never_called)
    return code, capsys.readouterr().out


def test_no_key_fails_and_says_how_to_make_one_and_where_it_goes(check, capsys, key):
    code, out = run(check, capsys, key)
    assert code == 1 and result_line(out) == 'RESULT: FAIL (no key)'
    assert 'MISSING' in out and 'Generate new private key' in out and str(key.parent) in out and 'never paste it' in out


def test_a_file_that_is_not_a_service_account_key_fails_before_anything_is_sent(check, capsys, key):
    key.parent.mkdir(parents=True)
    key.write_text('{"type": "authorized_user"}')
    code, out = run(check, capsys, key)
    assert code == 1 and result_line(out) == 'RESULT: FAIL (the key file)'
    assert 'cannot be used' in out and 'not a service account key' in out


def test_a_key_whose_private_key_cannot_be_read_fails_at_the_key_step(check, capsys, key):
    write_key_file(key, private_key='cut short')
    code, out = run(check, capsys, key)
    assert code == 1 and result_line(out) == 'RESULT: FAIL (the key file)' and 'holds a key that cannot be read' in out


def test_a_working_database_passes_leaves_nothing_behind_and_never_shows_the_private_key(check, capsys, key):
    write_key_file(key)
    backend = FakeBackend()
    backend.docs['users/usr_1'] = {'email': 'saji@example.com'}
    code, out = run(check, capsys, key, backend)
    assert code == 0 and result_line(out) == 'RESULT: PASS', out
    assert f'project ........ {PROJECT}' in out and f'firebase-adminsdk-test@{PROJECT}.iam.gserviceaccount.com' in out
    assert 'OK: written, read back and deleted.' in out and 'accounts in the database: 1' in out
    assert 'Storage: FIRESTORE' in out and 'photos never are' in out
    assert list(backend.docs) == ['users/usr_1'] and backend.commits == 2  # the test document was written, then deleted
    assert private_key_text() not in out and 'PRIVATE KEY' not in out and 'test-key-id' not in out


def test_a_database_with_its_own_name_is_shown_and_used(check, capsys, key):
    write_key_file(key)
    asked = []

    def make(settings):
        asked.append(settings.firestore_database)
        return FakeBackend()

    code = check.main([], settings=Settings(storage='auto', firebase_key=key, firestore_database='kiro-db'), make_backend=make)
    out = capsys.readouterr().out
    assert code == 0 and asked == ['kiro-db'] and 'database ....... kiro-db' in out


def test_storage_memory_is_pointed_out_even_when_the_database_works(check, capsys, key):
    write_key_file(key)
    code, out = run(check, capsys, key, FakeBackend(), storage='memory')
    assert code == 0 and 'STORAGE=memory, so it will NOT use the database' in out


class Refusing(FakeBackend):
    def __init__(self, message):
        super().__init__()
        self.message = message

    def commit(self, writes):
        raise StorageUnavailable(self.message)


@pytest.mark.parametrize(
    ('message', 'advice'),
    [
        ('saving failed with HTTP 404 NOT_FOUND: The database (default) does not exist for project p', 'Create database'),
        ('saving failed with HTTP 403 PERMISSION_DENIED: Cloud Firestore API has not been used in project p before or it is disabled.', 'switched off'),
        ('saving failed with HTTP 403 PERMISSION_DENIED: Missing or insufficient permissions.', 'not allowed to use this database'),
        ('Google refused the key (RefreshError: invalid_grant: Invalid JWT Signature.)', 'clock'),
        ('the database could not be reached (TransportError)', 'internet connection'),
    ],
)
def test_each_failure_says_what_went_wrong_and_what_to_do(check, capsys, key, message, advice):
    write_key_file(key)
    code, out = run(check, capsys, key, Refusing(message))
    assert code == 1 and result_line(out) == 'RESULT: FAIL (the database)'
    assert f'FAILED: {message}' in out and advice in out.split('What to do:')[1]


def test_help_explains_the_check(check, capsys):
    assert check.main(['--help']) == 0
    assert 'RESULT: PASS' in capsys.readouterr().out
