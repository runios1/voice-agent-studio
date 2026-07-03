"""Time, made injectable.

Calling-hours windows, retry backoff, and the rate limiter all reason about "now".
Threading a `Clock` through them (instead of calling `datetime.now()` directly)
makes every time-dependent rule deterministic under test: `ManualClock` lets a test
sit the campaign at 3am, advance an hour, and watch the window open — no real
sleeping, no flakiness.

Datetimes are tz-aware UTC. "Calling hours" are *local* hours (contract wording);
Phase 2 uses a single campaign timezone (`Scheduler.tz`, default UTC) — per-lead
timezones are a documented later refinement, not a schema change.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    """Production clock — wall-clock UTC."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class ManualClock:
    """Test clock. Time only moves when a test moves it (`advance` / `set`)."""

    def __init__(self, start: datetime):
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        from datetime import timedelta

        self._now = self._now + timedelta(seconds=seconds)

    def set(self, when: datetime) -> None:
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        self._now = when
