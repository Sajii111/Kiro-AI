"""Form checks, word for word the ones the website makes first (src/lib/validate.ts). Each returns a sentence to show,
or None when the value is fine. The server checks again because anyone can skip the website and call the API."""

from __future__ import annotations

import re

PROFILE_NAME_MAX = 24
READING_NAME_MAX = 40
PASSWORD_MIN = 8
MESSAGE_MAX = 500

_EMAIL = re.compile(r'[^\s@]+@[^\s@]+\.[^\s@]{2,}')
_LONG_DIGITS = re.compile(r'[0-9]{5,}')


def validate_profile_name(raw: str) -> str | None:
    name = raw.strip()
    if not name:
        return 'Please give the profile a name.'
    if len(name) > PROFILE_NAME_MAX:
        return f'Keep it to {PROFILE_NAME_MAX} characters or fewer.'
    if not all(ch.isalpha() or ch.isnumeric() or ch in " '’.-" for ch in name):
        return 'Keep it simple: letters and spaces are enough. Please leave out symbols, emails and phone numbers.'
    if _LONG_DIGITS.search(name):
        return 'That looks like a phone number. A first name or nickname is plenty.'
    return None


#: what a reading's name may hold besides letters, numbers and spaces
_READING_NAME_MARKS = "'’.,!?&:()-"


def clean_reading_name(raw: str) -> str:
    """A reading's name as it is kept: no spaces at the ends, and every run of spaces (or a line break) made one space.
    A name that is only spaces becomes the empty string, which means "no name"."""
    return ' '.join(raw.split())


def validate_reading_name(raw: str) -> str | None:
    """A reading's name is optional, so an empty one is fine: the reading is then called by its date. Kept as simple as a
    profile's name, for the same reason: nothing like an e-mail address or a phone number is saved by accident."""
    name = clean_reading_name(raw)
    if not name:
        return None
    if len(name) > READING_NAME_MAX:
        return f'Keep the name to {READING_NAME_MAX} characters or fewer.'
    if not all(ch.isalpha() or ch.isnumeric() or ch == ' ' or ch in _READING_NAME_MARKS for ch in name):
        return 'Keep the name simple: letters, numbers and spaces are enough. Please leave out symbols, emails and links.'
    if _LONG_DIGITS.search(name):
        return 'That looks like a phone number. A short name is plenty.'
    return None


def validate_display_name(raw: str) -> str | None:
    name = raw.strip()
    if not name:
        return 'Please tell us what to call you.'
    if len(name) > PROFILE_NAME_MAX:
        return f'Keep it to {PROFILE_NAME_MAX} characters or fewer.'
    return None


def validate_email(raw: str) -> str | None:
    email = raw.strip()
    if not email:
        return 'Please enter your email.'
    if not _EMAIL.fullmatch(email):
        return 'That email does not look right. Please check it.'
    return None


def validate_password(raw: str) -> str | None:
    if not raw:
        return 'Please enter a password.'
    if len(raw) < PASSWORD_MIN:
        return f'Use at least {PASSWORD_MIN} characters.'
    return None
