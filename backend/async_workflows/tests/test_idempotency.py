"""Replay safety — the same outcome event must never send two emails."""

from __future__ import annotations

from backend.async_workflows.clock import ManualClock
from backend.async_workflows.fixtures import build_pipeline, outcome_event
from backend.async_workflows.idempotency import InMemoryRunLedger, step_key


async def test_replayed_outcome_sends_email_once():
    p = build_pipeline(ManualClock())
    booked = outcome_event("booked", event_id="fixed-evt")

    await p.feed(booked)
    await p.feed(booked)  # redelivery
    await p.feed(booked)

    assert len(p.registry.email.calls) == 1
    assert len(p.registry.crm.calls) == 1


async def test_partial_run_resumes_without_redoing_first_step():
    # Simulate a crash after step 0 (email) by pre-seeding the ledger with its key,
    # then run: email is skipped as duplicate, CRM still executes.
    from backend.async_workflows.engine import LocalWorkflowEngine
    from backend.async_workflows.defaults import default_library
    from backend.async_workflows.mocks import (
        InMemoryEventSink,
        MockConnectionResolver,
        MockToolRegistry,
    )
    from backend.async_workflows.scheduler import FollowupScheduler
    from backend.async_workflows.models import Trigger

    clock = ManualClock()
    ledger = InMemoryRunLedger()
    registry = MockToolRegistry()
    sink = InMemoryEventSink()
    engine = LocalWorkflowEngine(
        library=default_library(),
        registry=registry,
        ledger=ledger,
        sink=sink,
        scheduler=FollowupScheduler(clock),
        clock=clock,
        connections=MockConnectionResolver(),
    )
    trigger = Trigger(run_id="run-1", tenant_id="t", lead_id="l", payload={"outcome": "booked"})
    await ledger.check_and_record(step_key("run-1", 0, "email"))  # pretend step 0 already ran

    run = await engine.run("booking_confirmation", trigger)

    assert registry.email.calls == []             # skipped as duplicate
    assert [c["status"] for c in registry.crm.calls] == ["meeting_booked"]
    assert [s.action for s in run.steps] == ["skipped_duplicate", "invoked"]
