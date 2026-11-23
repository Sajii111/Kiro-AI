"""One place that knows what time it is, so tests can move the clock."""

from __future__ import annotations

import time
from datetime import UTC, datetime


def now_ms() -> int:
    """Milliseconds since 1 January 1970 (the unit a guest's `expiresAt` uses)."""
    return int(time.time() * 1000)


def iso(ms: int | None = None) -> str:
    """An ISO 8601 timestamp in UTC, like 2026-11-08T09:30:00.123Z."""
    t = (now_ms() if ms is None else ms) / 1000
    d = datetime.fromtimestamp(t, tz=UTC)
    return d.strftime('%Y-%m-%dT%H:%M:%S.') + f'{d.microsecond // 1000:03d}Z'
