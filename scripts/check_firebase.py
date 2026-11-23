"""Checks that Kiro AI can use your Firebase project's database (Cloud Firestore). Run it once after you put the key in place.

    run.bat firebase                      Windows
    python scripts/check_firebase.py      the same, from any terminal (use the Python in backend/.venv)

What it does, in order:

    1  the key        looks for backend\\secrets\\firebase-service-account.json (or the file FIREBASE_KEY names) and reads the
                      project's name from it. The private key in it is NEVER printed.
    2  the database   signs in to Google as that service account, writes one small test document, reads it back and deletes
                      it again. Nothing about any person is written.
    3  what is saved  counts the accounts already in the database, and says whether the server will keep accounts there
                      (STORAGE in backend\\.env: auto, the default, uses the database whenever the key is there)

It ends with  RESULT: PASS  or  RESULT: FAIL  (exit code 0 or 1), and when something fails it says what to do.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'backend'
sys.path.insert(0, str(BACKEND))

if hasattr(sys.stdout, 'reconfigure'):  # a Windows console may not speak UTF-8; never let a print crash the check
    sys.stdout.reconfigure(errors='replace')

from app.core.config import read_settings
from app.store.persist import StorageUnavailable

#: what Google's answer says, and what to do about it
HINTS = (
    ('does not exist', (
        'The project has no Firestore database yet. In the Firebase console: Databases & Storage > Firestore > Create database. '
        '(If you gave the database its own name there, put  FIRESTORE_DATABASE=that-name  in backend\\.env.)'
    )),
    ('has not been used', 'The Firestore API is switched off for this project. Creating the database in the Firebase console switches it on; wait a minute and run this again.'),
    ('disabled', 'The Firestore API is switched off for this project. Creating the database in the Firebase console switches it on; wait a minute and run this again.'),
    ('PERMISSION_DENIED', 'The key is not allowed to use this database. Make a new key in the Firebase console (Project settings > Service accounts > Generate new private key) for the same project.'),
    ('invalid_grant', 'Google refused the key: it may have been deleted in the console, or the computer clock may be wrong. Make a new key and check the clock.'),
    ('RefreshError', 'Google refused the key: it may have been deleted in the console, or the computer clock may be wrong. Make a new key and check the clock.'),
    ('could not be reached', 'This computer could not reach Google. Check the internet connection (and any firewall or proxy), then run this again.'),
)


def say(text: str = '') -> None:
    print(text, flush=True)


def hint_for(message: str) -> str:
    for needle, hint in HINTS:
        if needle.lower() in message.lower():
            return hint
    return 'Read the message above. If it does not help, make a new key in the Firebase console and run this again.'


def open_database(settings):
    """The real connection, signed in with the key. Tests pass their own instead."""
    from app.store.firestore import FirestoreBackend

    return FirestoreBackend.from_key_file(settings.firebase_key, database=settings.firestore_database)


def run(settings=None, make_backend=open_database) -> int:
    settings = settings or read_settings()
    say('Kiro AI: checking the online database (Cloud Firestore)')
    say('')
    say('[1/3] The key')
    key = settings.firebase_key
    say(f'     {key} ... {"found" if key.is_file() else "MISSING"}')
    if not key.is_file():
        say('     Make one in the Firebase console: Project settings > Service accounts > Generate new private key.')
        say(f'     Rename the downloaded file to {key.name} and put it in {key.parent}')
        say('     (never paste it anywhere or send it to anyone).')
        say('')
        say('RESULT: FAIL (no key)')
        return 1
    from app.store.firestore import load_credentials

    try:
        info, _ = load_credentials(key)
    except ValueError as error:
        say(f'     That file cannot be used: {error}.')
        say('     Make a new key in the Firebase console (Project settings > Service accounts > Generate new private key).')
        say('')
        say('RESULT: FAIL (the key file)')
        return 1
    say(f'     project ........ {info["project_id"]}')
    say(f'     signs in as .... {info["client_email"]}   (the private key itself is never shown)')
    if settings.firestore_database != '(default)':
        say(f'     database ....... {settings.firestore_database}   (FIRESTORE_DATABASE in backend\\.env)')

    say('')
    say('[2/3] The database: one test document written, read back and deleted')
    try:
        db = make_backend(settings)
        path = f'checks/{uuid.uuid4().hex}'
        note = {'what': 'a test document from run.bat firebase; it is deleted straight away'}
        db.commit([('set', path, note)])
        back = db.get(path)
        db.commit([('delete', path, None)])
        gone = db.get(path) is None
    except StorageUnavailable as error:
        say(f'     FAILED: {error}')
        say(f'     What to do: {hint_for(str(error))}')
        say('')
        say('RESULT: FAIL (the database)')
        return 1
    if back != note or not gone:
        say('     FAILED: the document did not come back as it was written, or did not go away.')
        say('')
        say('RESULT: FAIL (the database)')
        return 1
    say('     OK: written, read back and deleted.')

    say('')
    say('[3/3] What is saved')
    try:
        accounts = len(db.list('users'))
    except StorageUnavailable as error:
        say(f'     could not count the accounts: {error}')
        accounts = None
    if accounts is not None:
        say(f'     accounts in the database: {accounts}')
    if settings.storage == 'memory':
        say('     The server is told STORAGE=memory, so it will NOT use the database. Remove that line from backend\\.env to use it.')
    else:
        say('     The server will keep accounts, their hand profiles, readings and chats here. Guest sessions are never saved,')
        say('     and photos never are. Restart run.bat if it is running: its window then says "Storage: FIRESTORE".')
    say('')
    say('RESULT: PASS')
    return 0


def main(argv: list[str], settings=None, make_backend=open_database) -> int:
    if argv and argv[0] in ('-h', '--help'):
        say(__doc__ or '')
        return 0
    return run(settings, make_backend)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
