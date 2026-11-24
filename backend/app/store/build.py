"""Which store the server uses: memory only, or memory plus the online database (see persist.py)."""

from __future__ import annotations

import logging

from app.core.config import Settings
from app.store.memory import MemoryStore
from app.store.persist import PersistentStore

log = logging.getLogger('kiro.store')


class StorageNotReady(RuntimeError):
    """STORAGE=firestore was asked for, but the key is missing or unusable. The message says which and what to do."""


def build_store(settings: Settings) -> MemoryStore:
    if settings.storage == 'memory':
        return MemoryStore(settings.guest_minutes, settings.signin_days)
    if settings.storage == 'auto' and not settings.firebase_key_given:
        return MemoryStore(settings.guest_minutes, settings.signin_days)
    try:
        from app.store.firestore import FirestoreBackend

        backend = FirestoreBackend.from_key_file(settings.firebase_key, database=settings.firestore_database, text=settings.firebase_key_json)
    except (ValueError, ImportError) as error:
        if settings.storage == 'firestore':
            raise StorageNotReady(f'STORAGE=firestore, but {error}. {where_the_key_goes(settings)}') from None
        log.warning('accounts are kept in memory only, because the Firebase key could not be used: %s', error)
        return MemoryStore(settings.guest_minutes, settings.signin_days)
    return PersistentStore(settings.guest_minutes, settings.signin_days, backend, where=f'Firestore project {backend.project_id}')


def where_the_key_goes(settings: Settings) -> str:
    """What to do about a missing or unusable key, in one sentence."""
    if settings.firebase_key_json.strip():
        return 'Paste the whole key file into the FIREBASE_KEY_JSON setting again (or base64 of it), or set STORAGE=memory.'
    return (
        f'Put the service account key at {settings.firebase_key}, or paste the whole key file into the FIREBASE_KEY_JSON setting '
        '(on a hosting service), or set STORAGE=memory.'
    )


def check_key(settings: Settings) -> tuple[str, str]:
    """(the Firebase project's name, '') when the key can be used, or ('', why not). Only the key is read (the file, or the
    FIREBASE_KEY_JSON setting): nothing is sent anywhere and the key itself is never returned, so the start-up window and the
    preflight can say it safely."""
    try:
        from app.store.firestore import load_credentials

        info, _ = load_credentials(settings.firebase_key, settings.firebase_key_json)
    except ImportError:
        return '', "Google's sign-in library is not installed (run.bat installs it)"
    except ValueError as error:
        return '', str(error)
    return info['project_id'], ''


def storage_name(store: MemoryStore) -> str:
    return 'firestore' if isinstance(store, PersistentStore) else 'memory'
