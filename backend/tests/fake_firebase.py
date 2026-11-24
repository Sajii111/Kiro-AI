"""Stand-ins for the online database and for a Firebase key, so that no test ever reaches Google.

FakeBackend keeps documents in a dictionary and answers the three calls persist.py makes (get, list, commit). write_key_file
makes a service account key file that Google's library accepts: its private key is made fresh while the tests run (it is never
typed into a file) and belongs to no account anywhere, so nothing signed with it is accepted by Google.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from app.store.persist import StorageUnavailable

PROJECT = 'kiro-test-project'


#: Firestore's limit on one document (1 MiB); the stand-in refuses a bigger one, as Firestore would
DOCUMENT_LIMIT = 1_048_576


class FakeBackend:
    """A database in a dictionary: path -> fields. `down = True` makes every call fail as if there were no network; a path
    that starts with something in `refuse` is refused, as a document Firestore will not take would be."""

    def __init__(self):
        self.docs: dict[str, dict] = {}
        self.down = False
        self.refuse: set[str] = set()
        self.commits = 0
        self.biggest = 0

    def get(self, path):
        if self.down:
            raise StorageUnavailable('the database could not be reached (ConnectionError)')
        found = self.docs.get(path)
        return dict(found) if found is not None else None

    def list(self, collection):
        if self.down:
            raise StorageUnavailable('the database could not be reached (ConnectionError)')
        prefix = collection + '/'
        return [(p[len(prefix) :], dict(f)) for p, f in self.docs.items() if p.startswith(prefix) and '/' not in p[len(prefix) :]]

    def commit(self, writes):
        if self.down:
            raise StorageUnavailable('the database could not be reached (ConnectionError)')
        for kind, path, fields in writes:  # all or none, like one Firestore commit
            if any(path.startswith(prefix) for prefix in self.refuse):
                raise StorageUnavailable(f'saving failed with HTTP 400 INVALID_ARGUMENT: {path} was refused')
            size = len(json.dumps(fields or {}, ensure_ascii=False).encode('utf-8'))
            if kind == 'set' and size > DOCUMENT_LIMIT:
                raise StorageUnavailable(f'saving failed with HTTP 400 INVALID_ARGUMENT: {path} is bigger than 1 MiB')
        self.commits += 1
        for kind, path, fields in writes:
            if kind == 'set':
                self.docs[path] = dict(fields)
                self.biggest = max(self.biggest, len(json.dumps(fields, ensure_ascii=False).encode('utf-8')))
            else:
                self.docs.pop(path, None)

    def under(self, prefix):
        return sorted(p for p in self.docs if p.startswith(prefix))


@cache
def private_key_text() -> str:
    """A new RSA key in the PEM form Google's library reads, made once per test run."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()


def write_key_file(path: Path, project: str = PROJECT, **changes) -> Path:
    """A key file shaped like the one the Firebase console makes. `changes` replaces or (with None) removes fields."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key_text(project, **changes), encoding='utf-8')
    return path


def key_text(project: str = PROJECT, **changes) -> str:
    """The text of such a key file, as a person would paste it into the FIREBASE_KEY_JSON setting (laid out over several lines,
    as the downloaded file is)."""
    return json.dumps(key_info(project, **changes), indent=2)


def key_info(project: str = PROJECT, **changes) -> dict:
    info = {
        'type': 'service_account',
        'project_id': project,
        'private_key_id': 'test-key-id',
        'private_key': private_key_text(),
        'client_email': f'firebase-adminsdk-test@{project}.iam.gserviceaccount.com',
        'client_id': '100000000000000000000',
        'token_uri': 'https://oauth2.googleapis.com/token',
    }
    for field, value in changes.items():
        if value is None:
            info.pop(field, None)
        else:
            info[field] = value
    return info
