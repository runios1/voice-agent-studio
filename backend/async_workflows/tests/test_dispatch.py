"""Outcome events -> the right workflow runs (the core P2-4 promise)."""

from __future__ import annotations

from contracts.events.schema import Event, EventType, Severity

from backend.async_workflows.clock import ManualClock
from backend.async_workflows.fixtures import build_pipeline, outcome_event


async def test_booked_sends_confirmation_and_writes_crm():
    p = build_pipeline(ManualClock())
    await p.feed(outcome_event("booked"))

    assert [c["template_id"] for c in p.registry.email.calls] == ["booking_confirmation"]
    assert [c["status"] for c in p.registry.crm.calls] == ["meeting_booked"]
    # both effects mirrored to the stream as tool.invoked
    invoked = [e for e in p.sink.events if e.type is EventType.TOOL_INVOKED]
    assert {e.payload["tool"] for e in invoked} == {"email", "crm"}
    # correlation ids propagate from the trigger onto emitted events
    assert all(e.tenant_id == "tenant-1" and e.lead_id == "lead-1" for e in invoked)


async def test_opted_out_records_crm_but_never_emails():
    p = build_pipeline(ManualClock())
    await p.feed(outcome_event("opted_out"))

    assert p.registry.email.calls == []
    assert [c["status"] for c in p.registry.crm.calls] == ["opted_out"]


async def test_unrouted_outcome_is_a_noop():
    p = build_pipeline(ManualClock())
    run = (await p.feed(outcome_event("not_qualified")))[0]
    assert run is None
    assert p.registry.email.calls == [] and p.registry.crm.calls == []


async def test_non_outcome_event_is_ignored():
    p = build_pipeline(ManualClock())
    other = Event(
        event_id="e1",
        type=EventType.CALL_STARTED,
        occurred_at=ManualClock().now(),
        severity=Severity.INFO,
        tenant_id="tenant-1",
    )
    assert await p.dispatcher.handle(other) is None
    assert p.sink.events == []
