"""Passwords and session tokens, with nothing but the standard library.

A password is never stored. What is stored is a salted scrypt hash, which is slow on purpose, so guessing is slow too.
A session token is 32 random bytes; the browser holds it in an httpOnly cookie and the server looks it up.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

# scrypt cost: 2**14 blocks of 8 x 128 bytes = 16 MiB and about 50 ms. A good default for sign-in on a small server.
_N, _R, _P = 2**14, 8, 1
_MAXMEM = 64 * 1024 * 1024


def hash_password(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    """Returns (salt, hash) for a password."""
    salt = salt or os.urandom(16)
    return salt, hashlib.scrypt(password.encode('utf-8'), salt=salt, n=_N, r=_R, p=_P, maxmem=_MAXMEM, dklen=32)


def verify_password(password: str, salt: bytes, expected: bytes) -> bool:
    _, actual = hash_password(password, salt)
    return hmac.compare_digest(actual, expected)


#: A hash to compare against when the email is unknown, so that "no such account" takes as long as "wrong password".
_DUMMY_SALT, _DUMMY_HASH = hash_password('not-a-real-password', b'\x00' * 16)


def burn_time(password: str) -> None:
    verify_password(password, _DUMMY_SALT, _DUMMY_HASH)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def new_id(prefix: str) -> str:
    """An opaque id like prf_3f9c2a71b04d6e58."""
    return f'{prefix}_{secrets.token_hex(8)}'
