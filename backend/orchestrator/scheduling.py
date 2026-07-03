"""When a lead may next be dialed — calling hours, retry backoff, rate limiting.

Everything here is driven by an injected `Clock`, so it is fully deterministic
under test (P2-D2 honors calling windows + retries *durably*, via `next_action_at`,
not via a live wall clock a crash would lose).

  * `Scheduler` — pure functions over an envelope + clock: is `now` inside the
    calling window, when does the next window open, and what `next_action_at` a
    retry should get (backoff, then pushed forward to the next open window).
  * `RateLimiter` — a sliding 60s window bounding dials to `calls_per_minute`. It
    reports the wait until the next free slot; the runner sleeps that long. Shared
    across a campaign's workers, so the cap is global to the campaign, not per-worker.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta

from contracts.campaign.model import GuardrailEnvelope
from backend.orchestrator.clock import Clock

# Retry backoff: attempt 1 already happened, so the Nth retry waits base * 2^(N-1),
# capped. Deliberately modest — a no-answer isn't an outage — and clamped so a long
# campaign can't schedule a dial days out.
_BACKOFF_BASE = timedelta(minutes=5)
_BACKOFF_CAP = timedelta(hours=2)


class Scheduler:
    """Calling-window + backoff math. `tz`-naive hour comparison in a single campaign
    timezone (default UTC); per-lead timezones are a later refinement (see clock.py)."""

    def __init__(self, clock: Clock):
        self.clock = clock

    def within_calling_hours(self, when: datetime, envelope: GuardrailEnvelope) -> bool:
        return envelope.calling_start_hour_local <= when.hour < envelope.calling_end_hour_local

    def next_window_open(self, when: datetime, envelope: GuardrailEnvelope) -> datetime:
        """The earliest instant >= `when` that falls inside the calling window."""
        if self.within_calling_hours(when, envelope):
            return when
        start = envelope.calling_start_hour_local
        candidate = when.replace(
            hour=start, minute=0, second=0, microsecond=0
        )
        if when.hour >= envelope.calling_end_hour_local or candidate <= when:
            # Past today's window (or exactly at its edge) -> tomorrow's opening.
            candidate = candidate + timedelta(days=1)
        return candidate

    def backoff_delay(self, attempts: int) -> timedelta:
        # attempts is the count already made (>=1 when we compute a retry).
        # Clamp the exponent first so a big attempt count can't overflow the multiply.
        exp = min(max(0, attempts - 1), 20)
        delay = _BACKOFF_BASE * (2 ** exp)
        return min(delay, _BACKOFF_CAP)

    def next_action_at(self, attempts: int, envelope: GuardrailEnvelope) -> datetime:
        """When a retrying lead becomes eligible again: now + backoff, then pushed
        forward to the next open calling window if that lands outside it."""
        earliest = self.clock.now() + self.backoff_delay(attempts)
        return self.next_window_open(earliest, envelope)


class RateLimiter:
    """Sliding-window limiter: at most `per_minute` dials in any trailing 60s."""

    def __init__(self, per_minute: int, clock: Clock):
        self.per_minute = max(1, per_minute)
        self.clock = clock
        self._stamps: deque[datetime] = deque()

    def _prune(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=60)
        while self._stamps and self._stamps[0] <= cutoff:
            self._stamps.popleft()

    def seconds_until_free(self) -> float:
        """0.0 if a dial may go now; otherwise seconds until the oldest dial ages out."""
        now = self.clock.now()
        self._prune(now)
        if len(self._stamps) < self.per_minute:
            return 0.0
        oldest = self._stamps[0]
        wait = 60.0 - (now - oldest).total_seconds()
        return max(0.0, wait)

    def record_dial(self) -> None:
        self._stamps.append(self.clock.now())
