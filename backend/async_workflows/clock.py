"""Injectable clock.

Follow-up delays ("send the nudge 24h later") are load-bearing here, and a test
that actually sleeps 24h is useless. Every time-dependent component (the scheduler,
emitted-event timestamps) reads *now* through this seam, so tests advance a
`ManualClock` deterministically instead of sleeping.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    """Real wall-clock, UTC-aware. Used in the demo / production."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class ManualClock:
    """Test clock. Starts at a fixed instant; `advance()` moves it forward so
    delayed follow-ups become due without any real waiting."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)
