"""Deferred follow-ups: delays honored, backoff, attempt-exhaustion, replay safety."""

from __future__ import annotations

from contracts.events.schema import EventType

from backend.async_workflows.backoff import backoff_seconds
from backend.async_workflows.clock import ManualClock
from backend.async_workflows.fixtures import build_pipeline, outcome_event


async def test_no_answer_schedules_then_fires_after_delay():
    clock = ManualClock()
    p = build_pipeline(clock, max_attempts=3)

    await p.feed(outcome_event("no_answer", attempts=1))
    # nothing sent yet — only a followup.scheduled event
    assert p.registry.email.calls == []
    scheduled = [e for e in p.sink.events if e.type is EventType.FOLLOWUP_SCHEDULED]
    assert len(scheduled) == 1

    # not yet due
    await p.tick()
    assert p.registry.email.calls == []

    # advance past the backoff for attempts=1 (1h) and fire
    clock.advance(backoff_seconds(1) + 1)
    await p.tick()
    assert [c["template_id"] for c in p.registry.email.calls] == ["sorry_we_missed_you"]


async def test_backoff_grows_with_attempts():
    assert backoff_seconds(1) < backoff_seconds(2) < backoff_seconds(3)
    assert backoff_seconds(99) == backoff_seconds(100)  # capped


async def test_exhausted_attempts_schedules_nothing():
    clock = ManualClock()
    p = build_pipeline(clock, max_attempts=3)

    run = (await p.feed(outcome_event("no_answer", attempts=3)))[0]
    assert run.steps[0].action == "skipped_exhausted"
    assert [e for e in p.sink.events if e.type is EventType.FOLLOWUP_SCHEDULED] == []

    clock.advance(10 ** 9)
    await p.tick()
    assert p.registry.email.calls == []


async def test_qualified_nurture_touch_fires_after_a_day():
    clock = ManualClock()
    p = build_pipeline(clock)

    await p.feed(outcome_event("qualified"))
    assert [c["status"] for c in p.registry.crm.calls] == ["qualified"]
    assert p.registry.email.calls == []

    clock.advance(23 * 3600)   # under the 24h delay
    await p.tick()
    assert p.registry.email.calls == []

    clock.advance(2 * 3600)    # now past 24h
    await p.tick()
    assert [c["template_id"] for c in p.registry.email.calls] == ["nurture_nudge"]


async def test_scheduled_followup_is_replay_safe_across_ticks():
    clock = ManualClock()
    p = build_pipeline(clock, max_attempts=3)

    # feed the same no-answer outcome twice: only one timer, one eventual email
    evt = outcome_event("no_answer", attempts=1, event_id="fixed")
    await p.feed(evt)
    await p.feed(evt)

    clock.advance(backoff_seconds(1) + 1)
    await p.tick()
    await p.tick()   # ticking again fires nothing new

    assert len(p.registry.email.calls) == 1
