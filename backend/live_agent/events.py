"""Event emission for Live sessions.

Mirrors `backend/voice_runtime/events.py` (same `EventSink` seam, same
`CollectingEventSink` mock, same append-only posture), adapted to `LiveCallContext`
(P4-2's frozen input) instead of `CallSession`. `LiveCallContext` carries no
`call_id` (it is stamped once per conversation, not part of the frozen contract), so
`GeminiLiveAgentSession` mints one per `run()` call and hands it to the emitter here.

The event *envelope* (`contracts/events.schema.Event`) is frozen; the event *bus*
(persistence, live subscribe, audit log) is P2-5's — at integration its sink drops in
behind this same `EventSink` Protocol, unchanged.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from contracts.events.schema import Event, EventType, Severity
from contracts.live_agent.interface import LiveCallContext


class EventSink(Protocol):
    """Where emitted events go. Phase-4 v1: `CollectingEventSink` (mock). Integration:
    the P2-5 append-only stream."""

    async def emit(self, event: Event) -> None: ...


class CollectingEventSink:
    """In-memory, append-only event sink for tests. There is deliberately no way to
    mutate or delete a recorded event through this object."""

    def __init__(self) -> None:
        self._events: list[Event] = []

    async def emit(self, event: Event) -> None:
        self._events.append(event)

    @property
    def events(self) -> list[Event]:
        return list(self._events)

    def of_type(self, event_type: EventType) -> list[Event]:
        return [e for e in self._events if e.type == event_type]


class LiveEventEmitter:
    """Stamps and forwards events for one Live conversation. Bound to a
    `LiveCallContext` + a minted `call_id` so every event inherits the correct
    tenant/campaign/lead/call/agent correlation ids (D-security: tenant always
    present)."""

    def __init__(self, sink: EventSink, ctx: LiveCallContext, call_id: str) -> None:
        self._sink = sink
        self._ctx = ctx
        self._call_id = call_id

    async def emit(
        self,
        event_type: EventType,
        payload: Optional[dict[str, Any]] = None,
        *,
        severity: Severity = Severity.INFO,
    ) -> None:
        ctx = self._ctx
        await self._sink.emit(
            Event(
                event_id=uuid.uuid4().hex,
                type=event_type,
                occurred_at=datetime.now(timezone.utc),
                severity=severity,
                tenant_id=ctx.tenant_id,
                campaign_id=ctx.campaign_id,
                lead_id=ctx.lead_id,
                call_id=self._call_id,
                agent_id=ctx.agent_id,
                payload=payload or {},
            )
        )
