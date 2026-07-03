"""INT-C tests — `seed_and_run` drives realistic live motion onto a SHARED event log.

No HTTP: we build the SAME two in-memory services INT-A's assembly wires (an
`OrchestratorService` whose sink is the `EventService`, per contract §4a/§4b) and
assert that a bounded run lands the expected event types — including the
`campaign.autopaused` trip that proves the kill switch fired through the shared
orchestrator, not a private log.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

import pytest

from contracts.config_schema.schema import AgentConfig, AgentMeta
from contracts.events.schema import Event, EventType
from backend.events.service import EventService
from backend.events.store import EventQuery, InMemoryEventStore
from backend.orchestrator.mocks import ScriptedDialer
from backend.orchestrator.service import ConfigSource, OrchestratorService
from backend import phase2_demo

TENANT = "dev-user"


# --- the frozen §4a adapter (INT-A owns the real one; replicated for an HTTP-free test)
class EventServiceSink:
    def __init__(self, service: EventService) -> None:
        self._svc = service

    async def emit(self, event: Event) -> None:
        await self._svc.emit(
            event.type, tenant_id=event.tenant_id, payload=event.payload,
            severity=event.severity, campaign_id=event.campaign_id,
            lead_id=event.lead_id, call_id=event.call_id, agent_id=event.agent_id,
            event_id=event.event_id, occurred_at=event.occurred_at,
        )


class _AnyAgentConfigSource:
    """Stub `ConfigSource` mirroring INT-A's: returns a default `AgentConfig` for any
    agent_id, owned by the querying tenant so the envelope clamp is happy."""

    def get_config(self, agent_id: str, tenant_id: str) -> Optional[AgentConfig]:
        now = datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc)
        return AgentConfig(
            meta=AgentMeta(id=agent_id, owner_user_id=tenant_id, created_at=now, updated_at=now)
        )


def _build_stack() -> tuple[OrchestratorService, EventService]:
    events = EventService(store=InMemoryEventStore())
    orch = OrchestratorService(
        config_source=_AnyAgentConfigSource(),
        dialer=ScriptedDialer(),
        sink=EventServiceSink(events),
    )
    return orch, events


def _types(events: EventService) -> list[EventType]:
    return [s.event.type for s in events.query(EventQuery(tenant_id=TENANT))]


async def _drive_until(events: EventService, target: EventType, task: asyncio.Task,
                       timeout: float = 2.0) -> None:
    """Poll the shared log until `target` appears, then return (caller sets stop)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if target in _types(events):
            return
        if task.done():  # surfaces any exception raised inside the run
            task.result()
            return
        await asyncio.sleep(0)
    raise AssertionError(f"{target} never landed within {timeout}s; saw {_types(events)}")


# --------------------------------------------------------------------------- #
async def test_seed_and_run_emits_full_lifecycle_and_autopause() -> None:
    orch, events = _build_stack()
    stop = asyncio.Event()

    task = asyncio.create_task(
        phase2_demo.seed_and_run(orch, events, tenant=TENANT, stop=stop, beat_seconds=0)
    )
    try:
        # Run until the auto-pause trips (proves control + produced events share a log),
        # then stop cleanly after a few ticks of motion.
        await _drive_until(events, EventType.CAMPAIGN_AUTOPAUSED, task)
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=2.0)

    seen = set(_types(events))
    expected = {
        EventType.CAMPAIGN_STARTED,      # from orch.authorize_campaign
        EventType.CALL_STARTED,
        EventType.DISCLOSURE_SPOKEN,     # compliance-critical, REQUIRED text present
        EventType.TOOL_INVOKED,
        EventType.SLOT_BOOKED,
        EventType.LEAD_OUTCOME,
        EventType.CALL_ENDED,
        EventType.GUARDRAIL_TRIPPED,
        EventType.CAMPAIGN_AUTOPAUSED,   # the kill-switch trip via the shared orch
    }
    missing = expected - seen
    assert not missing, f"missing event types: {missing}; saw {sorted(t.value for t in seen)}"


async def test_campaign_is_authorized_and_running() -> None:
    orch, events = _build_stack()
    stop = asyncio.Event()
    task = asyncio.create_task(
        phase2_demo.seed_and_run(orch, events, tenant=TENANT, stop=stop, beat_seconds=0)
    )
    try:
        await _drive_until(events, EventType.CALL_STARTED, task)
        campaigns = orch.list_campaigns(TENANT)
        assert len(campaigns) == 1
        camp = campaigns[0]
        assert camp.name == phase2_demo.DEMO_CAMPAIGN_NAME
        leads = orch.list_leads(camp.id, TENANT)
        assert len(leads) == len(phase2_demo._LEAD_SCRIPTS)
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=2.0)


async def test_payloads_pass_the_emit_boundary_validation() -> None:
    # Every emit goes through EventService.emit which validates per-type. If any demo
    # payload were malformed (e.g. missing the REQUIRED disclosure text or slot_start),
    # emit would raise EventValidationError and the run task would fail here.
    orch, events = _build_stack()
    stop = asyncio.Event()
    task = asyncio.create_task(
        phase2_demo.seed_and_run(orch, events, tenant=TENANT, stop=stop, beat_seconds=0)
    )
    try:
        await _drive_until(events, EventType.CAMPAIGN_RESUMED, task)
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=2.0)

    # Compliance-critical fields are actually present in the persisted record.
    rows = events.query(EventQuery(tenant_id=TENANT, types=frozenset({EventType.DISCLOSURE_SPOKEN})))
    assert rows and all(r.event.payload.get("text") for r in rows)
    booked = events.query(EventQuery(tenant_id=TENANT, types=frozenset({EventType.SLOT_BOOKED})))
    assert booked and all(r.event.payload.get("slot_start") for r in booked)


async def test_no_stop_runs_exactly_one_pass_and_terminates() -> None:
    # Safety valve: without a `stop`, the coroutine must not hang forever.
    orch, events = _build_stack()
    await asyncio.wait_for(
        phase2_demo.seed_and_run(orch, events, tenant=TENANT, beat_seconds=0),
        timeout=2.0,
    )
    seen = set(_types(events))
    assert EventType.CAMPAIGN_AUTOPAUSED in seen
    assert EventType.CAMPAIGN_RESUMED in seen
    # Exactly one campaign, one pass (one autopause).
    autopauses = events.query(
        EventQuery(tenant_id=TENANT, types=frozenset({EventType.CAMPAIGN_AUTOPAUSED}))
    )
    assert len(autopauses) == 1
