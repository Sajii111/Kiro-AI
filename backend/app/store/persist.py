"""Accounts, sign-ins and everything an account owns, kept in an online database as well as in memory.

The in-memory store (memory.py) stays the working copy: every route reads and changes it exactly as before, so nothing
else in the server had to change. This file adds three things on top of it:

  * An account, its sign-ins and its data are LOADED from the database the first time they are wanted after the server
    starts (a sign-in on another day, a restart, a new copy of the server on a host).
  * After every request that can change something, `flush()` compares each loaded account's data with what was last
    written and SAVES only what changed: new or edited documents are written, removed ones are deleted. A periodic flush
    and one at shutdown catch anything a request did not.
  * GUEST SESSIONS ARE NEVER SAVED. A guest's data lives in memory only and goes when the session ends, as the website
    promises. When a guest copies their readings into a new account, they become the account's and are saved from then on.

What is saved, one document each (see `docs/API_CONTRACT.md`, "Where the data is kept"):

    users/{userId}                         email, display name, the scrypt salt and hash of the password, created, chat-answer count
    emails/{sha256 of the lower-cased e-mail}   which user has that e-mail (so a sign-in needs one read, not a search)
    sessions/{sha256 of the cookie token}  which user a sign-in belongs to, and when it runs out (the token itself is never saved)
    users/{userId}/profiles/{profileId}    one hand profile
    users/{userId}/readings/{readingId}    one reading: the findings, the report, how it was made. NEVER a photo.
    users/{userId}/conversations/{id}      one chat: which reading it is about, its title, how many messages
    users/{userId}/conversations/{id}/messages/{messageId}   one chat message

Each document carries a few plain fields that are easy to read in the Firebase console (names, dates, which profile) and
the whole object as JSON in `data`, because a reading holds lists of points, which Firestore cannot store as nested lists.
Every message is a document of its own, so a long chat never comes near Firestore's limit of 1 MiB per document.

Each account's changes are written in a batch of their own, so a problem with one account's data can never hold up another's.

The database is reached through a small `Backend` (firestore.py talks to Google; the tests use a dictionary).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from collections.abc import Iterable
from typing import Protocol

from app.core.clock import now_ms
from app.schemas import Conversation, Message, Reading, StoredProfile
from app.store.memory import Account, Bucket, MemoryStore, SignIn

log = logging.getLogger('kiro.store')

#: ('set', path, fields) writes a whole document; ('delete', path, None) removes one
Write = tuple[str, str, dict | None]


class StorageUnavailable(Exception):
    """The database could not be reached or refused a request. The message is for the server's log, never for the website."""


class Backend(Protocol):
    def get(self, path: str) -> dict | None:
        """The fields of one document, or None when it does not exist."""

    def list(self, collection: str) -> list[tuple[str, dict]]:
        """(id, fields) of every document directly in a collection."""

    def commit(self, writes: list[Write]) -> None:
        """Applies the writes, in as few requests as the database allows (each request is all or none). Writing a document
        twice, or deleting one that is already gone, does no harm, so a commit that failed half-way can simply be repeated."""


def digest(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def email_key(email: str) -> str:
    return digest(email.strip().lower())


def token_key(token: str) -> str:
    return digest(token)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode('ascii')


def unb64(text: str) -> bytes:
    return base64.b64decode(text.encode('ascii'))


# ------------------------------------------------------------------ the documents


def account_doc(account: Account, model_replies: int) -> dict:
    return {
        'email': account.email,
        'emailLower': account.email.strip().lower(),
        'displayName': account.display_name,
        'salt': b64(account.salt),
        'passwordHash': b64(account.password_hash),
        'createdAt': account.created_at,
        'modelReplies': model_replies,
    }


def account_from(user_id: str, fields: dict) -> Account:
    return Account(
        id=user_id,
        email=fields['email'],
        display_name=fields.get('displayName', ''),
        salt=unb64(fields['salt']),
        password_hash=unb64(fields['passwordHash']),
        created_at=fields.get('createdAt', ''),
    )


def as_json(model) -> str:
    return json.dumps(model.model_dump(mode='json'), separators=(',', ':'), sort_keys=True, ensure_ascii=False)


def profile_doc(p: StoredProfile) -> dict:
    return {'name': p.name, 'createdAt': p.createdAt, 'data': as_json(p)}


def reading_doc(r: Reading) -> dict:
    return {'profileId': r.profileId, 'createdAt': r.createdAt, 'data': as_json(r)}


def conversation_doc(c: Conversation) -> dict:
    return {
        'readingId': c.readingId,
        'profileId': c.profileId,
        'title': c.title,
        'updatedAt': c.updatedAt,
        'messageCount': c.messageCount,
        'data': as_json(c),
    }


def message_doc(m: Message) -> dict:
    return {'role': m.role, 'createdAt': m.createdAt, 'data': as_json(m)}


def message_order(m: Message) -> tuple[str, bool]:
    """Oldest first; a question before its answer if they ever share a millisecond."""
    return m.createdAt, m.role != 'user'


def bucket_docs(user_id: str, bucket: Bucket) -> dict[str, dict]:
    """Every document an account's data makes, by path."""
    base = f'users/{user_id}'
    docs: dict[str, dict] = {}
    for p in bucket.profiles:
        docs[f'{base}/profiles/{p.id}'] = profile_doc(p)
    for r in bucket.readings:
        docs[f'{base}/readings/{r.id}'] = reading_doc(r)
    for c in bucket.conversations:
        docs[f'{base}/conversations/{c.id}'] = conversation_doc(c)
    known = {c.id for c in bucket.conversations}
    for m in bucket.messages:
        if m.conversationId in known:  # a message whose chat is gone is never saved (and is deleted with it)
            docs[f'{base}/conversations/{m.conversationId}/messages/{m.id}'] = message_doc(m)
    return docs


def bucket_from(profiles: Iterable[dict], readings: Iterable[dict], conversations: Iterable[dict], messages: Iterable[dict]) -> Bucket:
    bucket = Bucket()
    bucket.profiles = sorted((StoredProfile.model_validate_json(f['data']) for f in profiles), key=lambda p: p.createdAt)
    bucket.readings = sorted((Reading.model_validate_json(f['data']) for f in readings), key=lambda r: r.createdAt)
    bucket.conversations = sorted((Conversation.model_validate_json(f['data']) for f in conversations), key=lambda c: c.createdAt)
    bucket.messages = sorted((Message.model_validate_json(f['data']) for f in messages), key=message_order)
    return bucket


def fingerprint(fields: dict) -> str:
    return digest(json.dumps(fields, sort_keys=True, separators=(',', ':'), ensure_ascii=False))


# ------------------------------------------------------------------ the store


class PersistentStore(MemoryStore):
    """The memory store, with accounts and their data also kept in the database (guests are not)."""

    def __init__(self, guest_minutes: int, signin_days: int, backend: Backend, where: str = 'database'):
        super().__init__(guest_minutes, signin_days)
        self.backend = backend
        #: what to call the database in messages ("Firestore project kiro-ai")
        self.where = where
        #: path -> fingerprint of what was last written (or read), for every document of every loaded account
        self._saved: dict[str, str] = {}
        #: user id -> the chat-answer count last written
        self._saved_replies: dict[str, int] = {}
        self._flush_lock = asyncio.Lock()
        #: how many flushes failed since the server started (the health answer and the log say so)
        self.failed_flushes = 0

    # ------------------------------------------------------------ accounts
    def find_account(self, email: str) -> Account | None:
        found = super().find_account(email)
        if found is not None:
            return found
        index = self.backend.get(f'emails/{email_key(email)}')
        if not index:
            return None
        return self._load_account(index.get('userId', ''))

    def _load_account(self, user_id: str) -> Account | None:
        if not user_id:
            return None
        if user_id in self.accounts:
            return self.accounts[user_id]
        fields = self.backend.get(f'users/{user_id}')
        if not fields:
            return None
        account = account_from(user_id, fields)
        self.accounts[user_id] = account
        self._by_email[account.email.strip().lower()] = user_id
        self._saved_replies.setdefault(user_id, int(fields.get('modelReplies', 0) or 0))
        return account

    def add_account(self, email: str, display_name: str, salt: bytes, password_hash: bytes) -> Account:
        account = super().add_account(email, display_name, salt, password_hash)
        try:
            self.backend.commit(
                [
                    ('set', f'users/{account.id}', account_doc(account, 0)),
                    ('set', f'emails/{email_key(account.email)}', {'userId': account.id, 'email': account.email}),
                ]
            )
        except StorageUnavailable:
            # not saved, so it must not exist here either: the person sees an error and can try again
            self.accounts.pop(account.id, None)
            self._by_email.pop(account.email.strip().lower(), None)
            self.user_buckets.pop(account.id, None)
            raise
        self._saved_replies[account.id] = 0
        return account

    def bucket_of_user(self, user_id: str) -> Bucket:
        bucket = self.user_buckets.get(user_id)
        if bucket is not None:
            return bucket
        base = f'users/{user_id}'
        found: dict[str, dict] = {}  # path -> fields, for every document the account has
        kinds: dict[str, list[dict]] = {'profiles': [], 'readings': [], 'conversations': [], 'messages': []}
        collections = [(f'{base}/{kind}', kind) for kind in ('profiles', 'readings', 'conversations')]
        while collections:  # each chat's messages are listed once the chat itself has been found
            collection, kind = collections.pop(0)
            for doc_id, fields in self.backend.list(collection):
                found[f'{collection}/{doc_id}'] = fields
                kinds[kind].append(fields)
                if kind == 'conversations':
                    collections.append((f'{collection}/{doc_id}/messages', 'messages'))
        bucket = bucket_from(kinds['profiles'], kinds['readings'], kinds['conversations'], kinds['messages'])
        account = self.backend.get(base) or {}
        bucket.model_replies = int(account.get('modelReplies', 0) or 0)
        self._saved_replies[user_id] = bucket.model_replies
        for path, fields in found.items():
            self._saved[path] = fingerprint(fields)
        self.user_buckets[user_id] = bucket
        return bucket

    # ------------------------------------------------------------ sign-ins
    def start_sign_in(self, user_id: str) -> str:
        token = super().start_sign_in(user_id)
        expires = self._sign_ins[token].expires_at
        try:
            self.backend.commit([('set', f'sessions/{token_key(token)}', {'userId': user_id, 'expiresAt': expires})])
        except StorageUnavailable:
            self._sign_ins.pop(token, None)
            raise
        return token

    def account_for(self, token: str | None) -> Account | None:
        if not token:
            return None
        if token not in self._sign_ins:
            fields = self.backend.get(f'sessions/{token_key(token)}')
            if not fields:
                return None
            expires = int(fields.get('expiresAt', 0) or 0)
            if expires <= now_ms():
                self._forget_session(token)
                return None
            if self._load_account(fields.get('userId', '')) is None:
                return None
            self._sign_ins[token] = SignIn(fields['userId'], expires)
        account = super().account_for(token)
        if account is None:
            self._forget_session(token)
        return account

    def end_sign_in(self, token: str | None) -> None:
        super().end_sign_in(token)
        if token:
            self._forget_session(token)

    def _forget_session(self, token: str) -> None:
        try:
            self.backend.commit([('delete', f'sessions/{token_key(token)}', None)])
        except StorageUnavailable as error:
            log.warning('could not delete a sign-in from the database: %s', error)

    def sweep(self) -> int:
        expired = [t for t, s in self._sign_ins.items() if s.expires_at <= now_ms()]
        gone = super().sweep()
        if expired:
            try:
                self.backend.commit([('delete', f'sessions/{token_key(t)}', None) for t in expired])
            except StorageUnavailable as error:
                log.warning('could not delete ended sign-ins from the database: %s', error)
        return gone

    # ------------------------------------------------------------ saving
    def pending_writes(self) -> list[tuple[str, list[Write], dict[str, str | None], int | None]]:
        """What has to be written for the loaded accounts to match the database, one batch per account: (user id, the writes,
        the fingerprints they will leave (None for a deleted document), the chat-answer count they will leave or None)."""
        batches = []
        for user_id, bucket in self.user_buckets.items():
            account = self.accounts.get(user_id)
            if account is None:
                continue
            writes: list[Write] = []
            marks: dict[str, str | None] = {}
            docs = bucket_docs(user_id, bucket)
            for path, fields in docs.items():
                mark = fingerprint(fields)
                if self._saved.get(path) != mark:
                    writes.append(('set', path, fields))
                    marks[path] = mark
            prefix = f'users/{user_id}/'
            gone = [p for p in self._saved if p.startswith(prefix) and p not in docs]
            for path in sorted(gone, key=lambda p: -p.count('/')):  # a chat's messages before the chat itself
                writes.append(('delete', path, None))
                marks[path] = None
            replies = None
            if self._saved_replies.get(user_id) != bucket.model_replies:
                writes.append(('set', f'users/{user_id}', account_doc(account, bucket.model_replies)))
                replies = bucket.model_replies
            if writes:
                batches.append((user_id, writes, marks, replies))
        return batches

    async def flush(self) -> bool:
        """Saves what changed, each account in a batch of its own. Returns False when the database refused a batch or could not
        be reached (what was not saved is tried again next time; the other accounts' batches are saved all the same)."""
        async with self._flush_lock:
            saved_all = True
            for user_id, writes, marks, replies in self.pending_writes():
                try:
                    await asyncio.to_thread(self.backend.commit, writes)
                except StorageUnavailable as error:
                    self.failed_flushes += 1
                    saved_all = False
                    log.error('could not save %d change(s) for one account to the %s, will try again: %s', len(writes), self.where, error)
                    continue
                for path, mark in marks.items():
                    if mark is None:
                        self._saved.pop(path, None)
                    else:
                        self._saved[path] = mark
                if replies is not None:
                    self._saved_replies[user_id] = replies
            return saved_all
