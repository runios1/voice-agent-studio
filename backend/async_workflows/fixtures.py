"""Fixture `lead.outcome` events + a small assembly helper.

The event feed stands in for a P2-5 subscription: hand these to the dispatcher to
drive the whole post-call pipeline in tests and the demo.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from contracts.events.schema import Event, EventType

from .clock import Clock, SystemClock
from .defaults import default_library, default_routing
from .dispatcher import WorkflowDispatcher
from .engine import LocalWorkflowEngine
from .idempotency import InMemoryRunLedger
from .mocks import InMemoryEventSink, MockConnectionResolver, MockToolRegistry
from .scheduler import FollowupScheduler


def outcome_event(
    outcome: str,
    *,
    tenant_id: str = "tenant-1",
    campaign_id: str = "camp-1",
    lead_id: str = "lead-1",
    call_id: str = "call-1",
    agent_id: str = "agent-1",
    attempts: int = 0,
    event_id: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
    extra: Optional[dict[str, Any]] = None,
) -> Event:
    payload: dict[str, Any] = {"outcome": outcome, "attempts": attempts}
    if extra:
        payload.update(extra)
    return Event(
        event_id=event_id or str(uuid.uuid4()),
        type=EventType.LEAD_OUTCOME,
        occurred_at=occurred_at or datetime.now(timezone.utc),
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        lead_id=lead_id,
        call_id=call_id,
        agent_id=agent_id,
        payload=payload,
    )


def build_pipeline(clock: Optional[Clock] = None, *, max_attempts: Optional[int] = None):
    """Wire the full P2-4 pipeline with mocked contracts. Returns a small bundle so
    tests/demo can drive the dispatcher and then inspect the registry/sink/scheduler."""
    clock = clock or SystemClock()
    registry = MockToolRegistry()
    sink = InMemoryEventSink()
    ledger = InMemoryRunLedger()
    scheduler = FollowupScheduler(clock)
    engine = LocalWorkflowEngine(
        library=default_library(),
        registry=registry,
        ledger=ledger,
        sink=sink,
        scheduler=scheduler,
        clock=clock,
        connections=MockConnectionResolver(),
        max_attempts=max_attempts,
    )
    dispatcher = WorkflowDispatcher(engine=engine, routing=default_routing())
    return Pipeline(dispatcher, engine, scheduler, registry, sink, clock)


class Pipeline:
    def __init__(self, dispatcher, engine, scheduler, registry, sink, clock) -> None:
        self.dispatcher = dispatcher
        self.engine = engine
        self.scheduler = scheduler
        self.registry = registry
        self.sink = sink
        self.clock = clock

    async def feed(self, *events: Event):
        runs = []
        for event in events:
            runs.append(await self.dispatcher.handle(event))
        return runs

    async def tick(self):
        return await self.scheduler.tick(self.engine)
