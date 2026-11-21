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
    key = settings.firebase_key
    if settings.storage == 'auto' and not key.is_file():
        return MemoryStore(settings.guest_minutes, settings.signin_days)
    try:
        from app.store.firestore import FirestoreBackend

        backend = FirestoreBackend.from_key_file(key, database=settings.firestore_database)
    except (ValueError, ImportError) as error:
        if settings.storage == 'firestore':
            raise StorageNotReady(f'STORAGE=firestore, but {error}. Put the service account key at {key}, or set STORAGE=memory.') from None
        log.warning('accounts are kept in memory only, because the Firebase key could not be used: %s', error)
        return MemoryStore(settings.guest_minutes, settings.signin_days)
    return PersistentStore(settings.guest_minutes, settings.signin_days, backend, where=f'Firestore project {backend.project_id}')


def check_key(settings: Settings) -> tuple[str, str]:
    """(the Firebase project's name, '') when the key file can be used, or ('', why not). Only the file is read: nothing is
    sent anywhere and the key itself is never returned, so the start-up window and the preflight can say it safely."""
    try:
        from app.store.firestore import load_credentials

        info, _ = load_credentials(settings.firebase_key)
    except ImportError:
        return '', "Google's sign-in library is not installed (run.bat installs it)"
    except ValueError as error:
        return '', str(error)
    return info['project_id'], ''


def storage_name(store: MemoryStore) -> str:
    return 'firestore' if isinstance(store, PersistentStore) else 'memory'
