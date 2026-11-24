"""Talks to Cloud Firestore over its REST API, signed in as the project's service account.

The service account's key is the JSON file the Firebase console makes ("Project settings > Service accounts > Generate new
private key"), kept in backend/secrets/ and never committed. On a hosting service the same key can be pasted into the
FIREBASE_KEY_JSON setting instead (see read_key_text). Its contents are never logged or shown: messages name only the project.

Only plain fields are written (text, whole numbers, true/false), which is all persist.py needs. The REST API was chosen over
Google's Firestore library because it needs nothing beyond what the server already installs (google-auth and requests, which
the Gemini library brings), so there is no large extra download and nothing that must be compiled on Windows.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib.parse import quote

import requests
from google.auth import exceptions as auth_errors

from app.store.persist import StorageUnavailable, Write

API = 'https://firestore.googleapis.com/v1'
SCOPE = 'https://www.googleapis.com/auth/datastore'
#: the most writes sent in one commit request, and roughly the most bytes (Firestore refuses a request over 10 MiB)
COMMIT_LIMIT = 500
COMMIT_BYTES = 4_000_000
TIMEOUT_S = 15


def encode(value) -> dict:
    """One plain Python value as a Firestore Value."""
    if value is None:
        return {'nullValue': None}
    if isinstance(value, bool):
        return {'booleanValue': value}
    if isinstance(value, int):
        return {'integerValue': str(value)}
    if isinstance(value, float):
        return {'doubleValue': value}
    if isinstance(value, str):
        return {'stringValue': value}
    raise TypeError(f'only text, numbers, true/false and nothing can be stored here, not {type(value).__name__}')


def decode(value: dict):
    if 'stringValue' in value:
        return value['stringValue']
    if 'integerValue' in value:
        return int(value['integerValue'])
    if 'booleanValue' in value:
        return bool(value['booleanValue'])
    if 'doubleValue' in value:
        return float(value['doubleValue'])
    if 'nullValue' in value:
        return None
    raise ValueError(f'unexpected kind of value in the database: {sorted(value)}')


def to_fields(doc: dict) -> dict:
    return {key: encode(value) for key, value in doc.items()}


def from_fields(fields: dict | None) -> dict:
    return {key: decode(value) for key, value in (fields or {}).items()}


#: the setting that can hold the key as text instead of a file. Messages name it, since such a key has no file name.
KEY_SETTING = 'FIREBASE_KEY_JSON'


def checked_key(info, name: str) -> dict:
    """The key's contents, checked for the parts that are needed. `name` is what messages call it (a file name or the setting)."""
    if not isinstance(info, dict) or info.get('type') != 'service_account':
        raise ValueError(f'{name} is not a service account key (the Firebase console makes one under Service accounts)')
    for field in ('project_id', 'private_key', 'client_email'):
        if not info.get(field):
            raise ValueError(f'{name} has no {field}')
    return info


def read_key_file(path: Path) -> dict:
    """The service account key, checked for the parts that are needed. Raises ValueError with a plain reason."""
    try:
        info = json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise ValueError(f'there is no key file at {path}') from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError(f'{Path(path).name} is not a readable JSON key file') from None
    return checked_key(info, Path(path).name)


def read_key_text(text: str) -> dict:
    """The service account key given as text in FIREBASE_KEY_JSON, checked like a key file. It may be the key file's text pasted
    in as it is, or base64 of it (for a settings box that keeps only one line). Raises ValueError with a plain reason that never
    repeats the text."""
    raw = text.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in '"\'':  # some settings pages keep the quotes typed around a value
        raw = raw[1:-1].strip()
    if not raw.startswith('{'):
        try:
            raw = base64.b64decode(''.join(raw.split()), validate=True).decode('utf-8-sig')
        except ValueError:  # not base64, or base64 of something that is not text (binascii.Error and UnicodeDecodeError)
            raise ValueError(f"{KEY_SETTING} is neither the key file's text nor base64 of it") from None
    try:
        # strict=False: a settings page that turned the \n inside the private key into real line breaks still gives a usable key
        info = json.loads(raw, strict=False)
    except json.JSONDecodeError:
        raise ValueError(f'{KEY_SETTING} is not readable JSON (was the whole key file pasted in?)') from None
    return checked_key(info, KEY_SETTING)


def load_credentials(path: Path, text: str = ''):
    """(the key's contents, Google credentials made from it): from `text` (FIREBASE_KEY_JSON) when there is any, otherwise from
    the key file. Nothing is sent anywhere yet: this only proves the key can be read. Raises ValueError with a plain reason
    (never the key itself)."""
    from google.oauth2 import service_account

    if text.strip():
        info, name, how = read_key_text(text), KEY_SETTING, 'was it cut short when it was pasted in?'
    else:
        info, name, how = read_key_file(path), Path(path).name, 'was the file edited or cut short?'
    try:
        credentials = service_account.Credentials.from_service_account_info(info, scopes=[SCOPE])
    except ValueError:  # a private key that cannot be read, or a part missing that Google's library needs
        raise ValueError(f'{name} holds a key that cannot be read ({how})') from None
    return info, credentials


class FirestoreBackend:
    """persist.Backend for one project's default database."""

    def __init__(self, project_id: str, session, database: str = '(default)'):
        self.project_id = project_id
        self.session = session  # an authorised requests.Session (google.auth.transport.requests.AuthorizedSession)
        self.root = f'projects/{project_id}/databases/{database}/documents'

    @classmethod
    def from_key_file(cls, path: Path, database: str = '(default)', text: str = '') -> FirestoreBackend:
        """Signed in with the key file, or with the key given as text (FIREBASE_KEY_JSON) when `text` has any."""
        from google.auth.transport.requests import AuthorizedSession

        info, credentials = load_credentials(path, text)
        return cls(info['project_id'], AuthorizedSession(credentials), database=database)

    # ------------------------------------------------------------ the three things persist.py asks for
    def get(self, path: str) -> dict | None:
        response = self._send('GET', f'{API}/{self.root}/{quote(path)}')
        if self._not_there(response, 'reading a document'):
            return None
        self._check(response, 'reading a document')
        return from_fields(response.json().get('fields'))

    def list(self, collection: str) -> list[tuple[str, dict]]:
        found: list[tuple[str, dict]] = []
        token = ''
        while True:
            url = f'{API}/{self.root}/{quote(collection)}?pageSize=300' + (f'&pageToken={quote(token)}' if token else '')
            response = self._send('GET', url)
            if self._not_there(response, 'listing documents'):
                return found
            self._check(response, 'listing documents')
            body = response.json()
            for doc in body.get('documents', []):
                found.append((doc['name'].rsplit('/', 1)[-1], from_fields(doc.get('fields'))))
            token = body.get('nextPageToken', '')
            if not token:
                return found

    def commit(self, writes: list[Write]) -> None:
        for page in self._pages(writes):
            response = self._send('POST', f'{API}/{self.root}:commit', json={'writes': page})
            self._check(response, 'saving')

    def _pages(self, writes: list[Write]) -> list[list[dict]]:
        """The writes as Firestore wants them, in requests of at most COMMIT_LIMIT writes and about COMMIT_BYTES."""
        pages: list[list[dict]] = [[]]
        size = 0
        for kind, path, fields in writes:
            name = f'{self.root}/{path}'
            write = {'update': {'name': name, 'fields': to_fields(fields or {})}} if kind == 'set' else {'delete': name}
            weight = len(json.dumps(write, ensure_ascii=False).encode('utf-8'))
            if pages[-1] and (len(pages[-1]) >= COMMIT_LIMIT or size + weight > COMMIT_BYTES):
                pages.append([])
                size = 0
            pages[-1].append(write)
            size += weight
        return [page for page in pages if page]

    # ------------------------------------------------------------ plumbing
    def _send(self, method: str, url: str, json: dict | None = None):
        try:
            return self.session.request(method, url, json=json, timeout=TIMEOUT_S)
        except auth_errors.RefreshError as error:  # Google would not sign the key in: deleted in the console, or a wrong clock
            words = str(error.args[0]) if error.args else ''
            raise StorageUnavailable(f'Google refused the key (RefreshError: {words[:200]})') from None
        except (requests.RequestException, auth_errors.GoogleAuthError) as error:  # no network (or no way to Google's sign-in)
            raise StorageUnavailable(f'the database could not be reached ({type(error).__name__})') from None

    def _not_there(self, response, what: str) -> bool:
        """True when a 404 only means that there is no such document. A 404 because the database itself does not exist (it
        has not been created yet, or FIRESTORE_DATABASE names another one) is an error, not an empty answer."""
        if response.status_code != 404:
            return False
        if 'does not exist' in reason(response):
            self._check(response, what)
        return True

    def _check(self, response, what: str) -> None:
        if response.status_code < 300:
            return
        raise StorageUnavailable(f'{what} failed with HTTP {response.status_code} {reason(response)}'.strip())


def reason(response) -> str:
    """Google's own words for a refusal, for example  PERMISSION_DENIED: Missing or insufficient permissions."""
    try:
        error = response.json().get('error', {})
        return f"{error.get('status', '')}: {error.get('message', '')}".strip(': ')
    except (ValueError, AttributeError):
        return ''
