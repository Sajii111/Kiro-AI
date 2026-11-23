"""A small seeded random number generator, the same one the website's sample backend uses (mulberry32 and FNV-1a).

The stand-in reading for a given reading id is therefore always the same, which makes it repeatable in tests.
"""

from __future__ import annotations

from collections.abc import Callable

_MASK = 0xFFFFFFFF


def _imul(a: int, b: int) -> int:
    return (a * b) & _MASK


def rng(seed: int) -> Callable[[], float]:
    a = seed & _MASK

    def next_value() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & _MASK
        t = a
        t = _imul(t ^ (t >> 15), t | 1)
        t = (t ^ ((t + _imul(t ^ (t >> 7), t | 61)) & _MASK)) & _MASK
        return ((t ^ (t >> 14)) & _MASK) / 4294967296

    return next_value


def hash_string(text: str) -> int:
    """Turns any text into a number that can seed rng(). Same text, same number."""
    h = 0x811C9DC5
    for ch in text:
        h ^= ord(ch) & 0xFFFF
        h = _imul(h, 0x01000193)
    return h & _MASK
