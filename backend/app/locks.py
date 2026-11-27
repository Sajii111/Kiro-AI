"""Palm locks, the rules around them: which profiles a browser session can reach, the lockout after failed attempts, the key
that seals templates, and the attempt log.

The rules in one place:

  * A profile with a palm lock can be reached only while it is the profile OPEN in this browser session. Each session has at
    most one open profile, so opening another one locks the first again, and nothing of a locked profile (its readings, its
    chats, its counts) is ever served to a session that has not unlocked it.
  * A locked profile opens with its palm (a successful unlock). An open profile left alone for `palm_idle_minutes` locks itself
    again, and so does every profile when the server restarts (which profile is open is kept in memory only).
  * Profiles without a lock open with a click, as before.
  * Five failed palm attempts on one profile within ten minutes lock it out for five minutes. An Invalid Image is not a failed
    attempt (nobody was refused: the photo was), and a success starts the count again.
  * The profile cannot be switched while a reading is being made in the session.
  * Guests cannot lock a profile: a lock is for an account that lasts.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet
from fastapi import Request

from app.core.clock import iso, now_ms
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import new_id
from app.cv.biometric.config import DEFAULT, ENGINE_VERSION
from app.cv.biometric.match import Calibration, CalibrationError, load_calibration
from app.cv.biometric.template import new_key
from app.deps import Caller
from app.schemas import Attempt, AttemptKind, StoredLock, StoredProfile
from app.store.memory import Bucket, MemoryStore, OpenProfile

log = logging.getLogger('kiro.locks')

#: failed attempts that lock a profile out, within this window, for this long
FAILURES = 5
WINDOW_MS = 10 * 60_000
LOCKOUT_MS = 5 * 60_000


# ------------------------------------------------------------------ the key and the calibration


def resolve_key(settings: Settings, persistent: bool) -> str:
    """The key that seals templates.

    PALM_TEMPLATE_KEY wins when it is set (that is how a hosted copy gets one). Otherwise, with the online database, the key
    is kept in backend/secrets/palm-template.key and made there on the first start: locks saved in the database must still
    open after a restart. With memory-only storage the locks go when the server stops, so a fresh key each start is enough
    (and nothing is written)."""
    if settings.palm_key:
        check_key(settings.palm_key, 'PALM_TEMPLATE_KEY')
        return settings.palm_key
    if not persistent or settings.env == 'test':
        return new_key()
    path = Path(settings.palm_key_file)
    if path.is_file():
        key = path.read_text(encoding='utf-8').strip()
        check_key(key, str(path))
        return key
    key = new_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key + '\n', encoding='utf-8')
    log.info('made a new key for palm-lock templates in %s (keep it: locks need it to open)', path)
    return key


def check_key(key: str, where: str) -> None:
    try:
        Fernet(key)
    except (ValueError, TypeError) as e:
        raise RuntimeError(f'The palm-lock key in {where} is not a valid key (it must be 44 characters made by the server). Remove it and the server makes a new one; palm locks made with the old key will need to be set up again.') from e


class PalmService:
    """What the palm lock needs from the server: the key, the calibration, and the hand model."""

    def __init__(self, settings: Settings, persistent: bool):
        self.key = resolve_key(settings, persistent)
        self.idle_ms = settings.palm_idle_minutes * 60_000
        self.settings = DEFAULT
        self.calibration: Calibration | None
        self.problem: str | None = None
        try:
            self.calibration = load_calibration()
        except CalibrationError as e:
            self.calibration = None
            self.problem = f'The palm lock is switched off: {e}'
            log.error('%s', self.problem)

    def ready(self, finder) -> str | None:
        """Why the palm lock cannot work right now, or None when it can."""
        if self.problem:
            return self.problem
        if finder is None:
            return 'The palm lock needs the hand model, which is not loaded on this server. Run  run.bat models  once, then start the server again.'
        return None

    def require(self, finder) -> Calibration:
        problem = self.ready(finder)
        if problem:
            raise ApiError('unavailable', problem)
        assert self.calibration is not None
        return self.calibration


# ------------------------------------------------------------------ which profile is open


def open_id(store: MemoryStore, caller: Caller, idle_ms: int) -> str | None:
    """The profile open in the caller's session, or None. A locked profile left alone too long is closed here (locked again)."""
    entry = store.open_profiles.get(caller.session_key)
    if entry is None:
        return None
    now = now_ms()
    if caller.bucket.profile(entry.profile_id) is None:
        store.open_profiles.pop(caller.session_key, None)
        return None
    if caller.bucket.lock_of(entry.profile_id) is not None and now - entry.last_seen > idle_ms:
        store.open_profiles.pop(caller.session_key, None)
        return None
    entry.last_seen = now
    return entry.profile_id


def current_open(request: Request, caller: Caller) -> str | None:
    """`open_id` for the caller of a request."""
    return open_id(request.app.state.store, caller, request.app.state.palm.idle_ms)


def can_reach(bucket: Bucket, profile_id: str, open_profile: str | None) -> bool:
    return bucket.lock_of(profile_id) is None or profile_id == open_profile


def locked_error(profile: StoredProfile) -> ApiError:
    return ApiError('locked', f'“{profile.name}” is locked with a palm. Unlock it with its palm first.', extra={'profileId': profile.id})


def require_reach(bucket: Bucket, profile_id: str, open_profile: str | None) -> None:
    profile = bucket.profile(profile_id)
    if profile is not None and not can_reach(bucket, profile_id, open_profile):
        raise locked_error(profile)


def set_open(store: MemoryStore, caller: Caller, profile_id: str | None) -> None:
    """Opens a profile in the caller's session (None closes the one that is open). Refused while a reading is being made for
    another profile: its result belongs to the profile it was started in."""
    current = store.open_profiles.get(caller.session_key)
    switching = (current.profile_id if current else None) != profile_id
    if switching and store.busy.get(caller.session_key, 0) > 0:
        raise ApiError('conflict', 'A reading is still being made. Wait until it has finished, then switch profiles.')
    if profile_id is None:
        store.open_profiles.pop(caller.session_key, None)
    else:
        store.open_profiles[caller.session_key] = OpenProfile(profile_id, now_ms())


# ------------------------------------------------------------------ lockout


def at_ms(text: str) -> int:
    return int(datetime.fromisoformat(text).timestamp() * 1000)


def locked_out_until(lock: StoredLock, now: int | None = None) -> int | None:
    now = now_ms() if now is None else now
    return lock.lockedUntil if lock.lockedUntil and lock.lockedUntil > now else None


def lockout_error(lock: StoredLock, until: int) -> ApiError:
    minutes = max(1, round((until - now_ms()) / 60_000))
    return ApiError(
        'locked_out',
        f'Too many palm attempts failed on this profile, so it is locked for now. Try again in about {minutes} minute{"s" if minutes != 1 else ""}.',
        extra={'profileId': lock.profileId, 'lockedUntil': until},
    )


def after_failure(bucket: Bucket, lock: StoredLock, now: int | None = None) -> int | None:
    """Counts the failed attempts that matter (in the last ten minutes, since the last success and since any earlier lockout
    ended) and locks the profile out when there are enough. Returns the end of the new lockout, or None."""
    now = now_ms() if now is None else now
    since = max(now - WINDOW_MS, lock.lockedUntil or 0)
    for a in reversed(bucket.attempts):
        if a.profileId == lock.profileId and a.kind in ('unlock', 'test') and a.outcome == 'success':
            since = max(since, at_ms(a.at) + 1)
            break
    fails = sum(1 for a in bucket.attempts if a.profileId == lock.profileId and a.kind in ('unlock', 'test') and a.outcome == 'failed' and at_ms(a.at) >= since)
    if fails >= FAILURES:
        lock.lockedUntil = now + LOCKOUT_MS
        return lock.lockedUntil
    return None


# ------------------------------------------------------------------ the attempt log


def log_event(bucket: Bucket, profile: StoredProfile, kind: AttemptKind, reason: str, **fields) -> Attempt:
    """Writes one line to the attempt log (never a photo, never a template) and returns it."""
    attempt = Attempt(
        id=fields.pop('id', None) or new_id('att'),
        profileId=profile.id,
        profileName=profile.name,
        kind=kind,
        at=fields.pop('at', None) or iso(),
        reason=reason,
        engineVersion=ENGINE_VERSION,
        **fields,
    )
    bucket.log(attempt)
    return attempt
