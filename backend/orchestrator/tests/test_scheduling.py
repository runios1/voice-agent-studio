"""Calling-window math, retry backoff, and the sliding-window rate limiter."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from contracts.campaign.model import GuardrailEnvelope
from backend.orchestrator.clock import ManualClock
from backend.orchestrator.scheduling import RateLimiter, Scheduler


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, 2, hour, minute, tzinfo=timezone.utc)


def test_within_calling_hours():
    sched = Scheduler(ManualClock(_at(10)))
    env = GuardrailEnvelope(calling_start_hour_local=8, calling_end_hour_local=20)
    assert sched.within_calling_hours(_at(8), env) is True
    assert sched.within_calling_hours(_at(19, 59), env) is True
    assert sched.within_calling_hours(_at(20), env) is False   # end is exclusive
    assert sched.within_calling_hours(_at(7, 59), env) is False


def test_next_window_open_same_day_and_next_day():
    sched = Scheduler(ManualClock(_at(6)))
    env = GuardrailEnvelope(calling_start_hour_local=8, calling_end_hour_local=20)
    # Before today's window -> today at 08:00.
    assert sched.next_window_open(_at(6), env) == _at(8)
    # After today's window -> tomorrow at 08:00.
    after = sched.next_window_open(_at(21), env)
    assert after == _at(8) + timedelta(days=1)
    # Already inside -> unchanged.
    assert sched.next_window_open(_at(12, 30), env) == _at(12, 30)


def test_backoff_grows_and_caps():
    sched = Scheduler(ManualClock(_at(10)))
    assert sched.backoff_delay(1) == timedelta(minutes=5)
    assert sched.backoff_delay(2) == timedelta(minutes=10)
    assert sched.backoff_delay(3) == timedelta(minutes=20)
    assert sched.backoff_delay(50) == timedelta(hours=2)  # capped


def test_next_action_at_pushed_into_window():
    # 19:58 + 5m backoff = 20:03, past the 20:00 close -> tomorrow 08:00.
    clock = ManualClock(_at(19, 58))
    sched = Scheduler(clock)
    env = GuardrailEnvelope(calling_start_hour_local=8, calling_end_hour_local=20)
    assert sched.next_action_at(1, env) == _at(8) + timedelta(days=1)


def test_rate_limiter_sliding_window():
    clock = ManualClock(_at(10))
    rl = RateLimiter(per_minute=2, clock=clock)
    assert rl.seconds_until_free() == 0.0
    rl.record_dial()
    rl.record_dial()
    # Third dial must wait ~60s for the oldest to age out.
    assert rl.seconds_until_free() == 60.0
    clock.advance(60)
    assert rl.seconds_until_free() == 0.0
