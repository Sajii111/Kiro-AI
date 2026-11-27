"""Where the server keeps accounts, guest sessions and everything they own: in memory, for now.

PHASE 1 ONLY. Everything here is lost when the server restarts (accounts included). Phase 4 replaces this file with
Firebase Authentication and Cloud Firestore behind the same methods; the routes and the website do not change.

Two rules this file is built around:

  * One bucket per owner. Every profile, reading, conversation and message lives in exactly one Bucket, and a request
    can only ever reach its own caller's bucket. There is no query that spans buckets, so one account cannot see
    another's data even by guessing an id: that id simply is not in its bucket (and the answer is 404, never 403).
  * Photos are never kept. Only findings, reports and chats are, and only here.

All of this runs on the server's single event-loop thread (routes are `async def`, and the heavy image work runs in
worker threads that never touch the store), so no locking is needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.clock import iso, now_ms
from app.core.security import new_id, new_token
from app.schemas import (
    Attempt,
    Conversation,
    DataCounts,
    HandProfile,
    Message,
    Reading,
    StoredLock,
    StoredProfile,
)

#: the attempt log keeps this many lines per account; the oldest go first
ATTEMPT_LOG_MAX = 500


@dataclass
class Bucket:
    """Everything one owner (an account or a guest session) holds."""

    profiles: list[StoredProfile] = field(default_factory=list)
    readings: list[Reading] = field(default_factory=list)
    conversations: list[Conversation] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    #: how many chat answers the language model has been asked for in this bucket. It is a limit on use, not a piece of the
    #: person's data: it is not exported, and deleting the data does not reset it.
    model_replies: int = 0
    #: palm locks, at most one per profile (only accounts have them: a guest cannot lock a profile)
    locks: list[StoredLock] = field(default_factory=list)
    #: the attempt log: every palm attempt and every change to a lock, oldest first
    attempts: list[Attempt] = field(default_factory=list)

    # ---- lookups: each returns None for an id that is not in THIS bucket
    def profile(self, id_: str) -> StoredProfile | None:
        return next((p for p in self.profiles if p.id == id_), None)

    def reading(self, id_: str) -> Reading | None:
        return next((r for r in self.readings if r.id == id_), None)

    def conversation(self, id_: str) -> Conversation | None:
        return next((c for c in self.conversations if c.id == id_), None)

    def messages_of(self, conversation_id: str) -> list[Message]:
        return [m for m in self.messages if m.conversationId == conversation_id]

    def lock_of(self, profile_id: str) -> StoredLock | None:
        return next((k for k in self.locks if k.profileId == profile_id), None)

    def set_lock(self, lock: StoredLock) -> None:
        self.locks = [k for k in self.locks if k.profileId != lock.profileId] + [lock]

    def drop_lock(self, profile_id: str) -> bool:
        before = len(self.locks)
        self.locks = [k for k in self.locks if k.profileId != profile_id]
        return len(self.locks) < before

    def log(self, attempt: Attempt) -> None:
        self.attempts.append(attempt)
        if len(self.attempts) > ATTEMPT_LOG_MAX:
            self.attempts = self.attempts[-ATTEMPT_LOG_MAX:]

    # ---- numbers
    def counts(self) -> DataCounts:
        return DataCounts(
            profiles=len(self.profiles), readings=len(self.readings), conversations=len(self.conversations), messages=len(self.messages)
        )

    def as_profile(self, p: StoredProfile, open_id: str | None = None) -> HandProfile:
        """A stored profile plus the counts the screens show. `open_id` is the profile open in the caller's session: any other
        profile with a palm lock is shown as locked, without its counts."""
        lock = self.lock_of(p.id)
        locked = lock is not None and p.id != open_id
        if locked:
            count, last = 0, None
        else:
            mine = [r for r in self.readings if r.profileId == p.id]
            count, last = len(mine), max((r.createdAt for r in mine), default=None)
        return HandProfile(
            **p.model_dump(),
            readingCount=count,
            lastReadingAt=last,
            lock=lock.summary() if lock else None,
            locked=locked,
            open=p.id == open_id,
        )

    # ---- cascade deletes: what goes is counted, and the counts are quoted back to the person
    def drop_conversations(self, ids: set[str]) -> tuple[int, int]:
        """Removes conversations and their messages. Returns (conversations, messages) removed."""
        messages = sum(1 for m in self.messages if m.conversationId in ids)
        conversations = sum(1 for c in self.conversations if c.id in ids)
        self.messages = [m for m in self.messages if m.conversationId not in ids]
        self.conversations = [c for c in self.conversations if c.id not in ids]
        return conversations, messages

    def drop_readings(self, ids: set[str]) -> tuple[int, int, int]:
        """Removes readings with their conversations and messages. Returns (readings, conversations, messages)."""
        readings = sum(1 for r in self.readings if r.id in ids)
        convo_ids = {c.id for c in self.conversations if c.readingId in ids}
        conversations, messages = self.drop_conversations(convo_ids)
        self.readings = [r for r in self.readings if r.id not in ids]
        return readings, conversations, messages

    def drop_profile(self, id_: str) -> DataCounts:
        reading_ids = {r.id for r in self.readings if r.profileId == id_}
        readings, conversations, messages = self.drop_readings(reading_ids)
        removed = len(self.profiles)
        self.profiles = [p for p in self.profiles if p.id != id_]
        self.drop_lock(id_)  # the attempt log keeps its lines: it is the account's record, not the profile's
        return DataCounts(profiles=removed - len(self.profiles), readings=readings, conversations=conversations, messages=messages)

    def clear(self) -> DataCounts:
        counts = self.counts()
        self.profiles, self.readings, self.conversations, self.messages = [], [], [], []
        self.locks, self.attempts = [], []
        return counts


@dataclass
class Account:
    id: str
    email: str
    display_name: str
    salt: bytes
    password_hash: bytes
    created_at: str


@dataclass
class GuestSession:
    id: str
    expires_at: int  # milliseconds since 1 January 1970
    bucket: Bucket = field(default_factory=Bucket)


@dataclass
class SignIn:
    user_id: str
    expires_at: int


@dataclass
class OpenProfile:
    """The one hand profile open in a browser session. Kept in memory only: a restart locks every profile again."""

    profile_id: str
    #: milliseconds since 1970 of the last request that used it; a profile left alone for too long locks itself again
    last_seen: int


def user_key(token: str) -> str:
    """The session key of a signed-in browser: its sign-in token (kept in memory only, like the token itself)."""
    return f'user:{token}'


def guest_key(guest_id: str) -> str:
    return f'guest:{guest_id}'


class MemoryStore:
    def __init__(self, guest_minutes: int, signin_days: int):
        self.guest_ms = guest_minutes * 60_000
        self.signin_ms = signin_days * 86_400_000
        self.accounts: dict[str, Account] = {}
        self._by_email: dict[str, str] = {}
        self.user_buckets: dict[str, Bucket] = {}
        self._sign_ins: dict[str, SignIn] = {}  # token -> sign-in
        self.guests: dict[str, GuestSession] = {}  # guest id -> session
        self._guest_tokens: dict[str, str] = {}  # token -> guest id
        #: session key (see deps.Caller.session_key) -> the profile open in that session
        self.open_profiles: dict[str, OpenProfile] = {}
        #: session key -> readings being made right now (a profile cannot be switched while one is)
        self.busy: dict[str, int] = {}

    # ------------------------------------------------------------ accounts
    def find_account(self, email: str) -> Account | None:
        id_ = self._by_email.get(email.strip().lower())
        return self.accounts.get(id_) if id_ else None

    def add_account(self, email: str, display_name: str, salt: bytes, password_hash: bytes) -> Account:
        account = Account(new_id('usr'), email.strip(), display_name.strip(), salt, password_hash, iso())
        self.accounts[account.id] = account
        self._by_email[email.strip().lower()] = account.id
        self.user_buckets[account.id] = Bucket()
        return account

    def bucket_of_user(self, user_id: str) -> Bucket:
        return self.user_buckets.setdefault(user_id, Bucket())

    # ------------------------------------------------------------ sign-in sessions
    def start_sign_in(self, user_id: str) -> str:
        token = new_token()
        self._sign_ins[token] = SignIn(user_id, now_ms() + self.signin_ms)
        return token

    def account_for(self, token: str | None) -> Account | None:
        """The account behind a sign-in token, or None when the token is unknown or has run out."""
        if not token:
            return None
        sign_in = self._sign_ins.get(token)
        if not sign_in:
            return None
        if sign_in.expires_at <= now_ms():
            del self._sign_ins[token]
            return None
        return self.accounts.get(sign_in.user_id)

    def end_sign_in(self, token: str | None) -> None:
        if token:
            self._sign_ins.pop(token, None)
            self.open_profiles.pop(user_key(token), None)

    # ------------------------------------------------------------ guest sessions
    def start_guest(self) -> tuple[str, GuestSession]:
        guest = GuestSession(new_id('gst'), now_ms() + self.guest_ms)
        token = new_token()
        self.guests[guest.id] = guest
        self._guest_tokens[token] = guest.id
        return token, guest

    def guest_for(self, token: str | None) -> GuestSession | None:
        """The live guest session behind a token. A session that has run out is deleted on the spot, data and all."""
        if not token:
            return None
        guest_id = self._guest_tokens.get(token)
        guest = self.guests.get(guest_id) if guest_id else None
        if guest is None:
            return None
        if guest.expires_at <= now_ms():
            self.end_guest(guest.id)
            return None
        return guest

    def end_guest(self, guest_id: str) -> None:
        """Deletes a guest session and everything in it."""
        guest = self.guests.pop(guest_id, None)
        if guest:
            guest.bucket.clear()
        self.open_profiles.pop(guest_key(guest_id), None)
        for token in [t for t, g in self._guest_tokens.items() if g == guest_id]:
            del self._guest_tokens[token]

    def end_guest_by_token(self, token: str | None) -> None:
        guest_id = self._guest_tokens.get(token) if token else None
        if guest_id:
            self.end_guest(guest_id)
        elif token:
            self._guest_tokens.pop(token, None)

    # ------------------------------------------------------------ housekeeping
    def sweep(self) -> int:
        """Deletes every guest session and sign-in that has run out. Returns how many guest sessions went."""
        now = now_ms()
        gone = [g.id for g in self.guests.values() if g.expires_at <= now]
        for guest_id in gone:
            self.end_guest(guest_id)
        for token in [t for t, s in self._sign_ins.items() if s.expires_at <= now]:
            del self._sign_ins[token]
            self.open_profiles.pop(user_key(token), None)
        return len(gone)
