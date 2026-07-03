"""Event emission — the P2-5 seam.

The event *envelope* (`contracts/events/schema.Event`) is frozen; the event *bus*
(persistence, live subscribe, immutable audit log) is P2-5's, and is NOT merged
yet. So this module defines the minimal seam the voice runtime emits through — an
`EventSink` protocol — and a `CollectingEventSink` mock that CI runs against. At
integration the real P2-5 sink replaces `CollectingEventSink`; nothing in the engine
changes (it only ever sees `EventSink.emit`).

`EventEmitter` stamps every event with the call's correlation ids (D-security: tenant
is ALWAYS present), a fresh `event_id`, and `occurred_at`, so a handler never has to
remember to set them. Payloads deliberately carry no raw PII — phone numbers are
masked here, not at the call sites.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from contracts.events.schema import Event, EventType, Severity
from contracts.voice_runtime.interface import CallSession


class EventSink(Protocol):
    """Where emitted events go. Phase-2 v1: `CollectingEventSink` (mock). Integration:
    the P2-5 append-only stream. The engine depends only on this one method."""

    async def emit(self, event: Event) -> None: ...


class CollectingEventSink:
    """In-memory, append-only event sink for tests and the demo. Mirrors the P2-5
    invariant that the log is append-only — there is deliberately no way to mutate or
    delete a recorded event through this object."""

    def __init__(self) -> None:
        self._events: list[Event] = []

    async def emit(self, event: Event) -> None:
        self._events.append(event)

    @property
    def events(self) -> list[Event]:
        # A copy so callers can't splice the log; append-only is the whole point.
        return list(self._events)

    def of_type(self, event_type: EventType) -> list[Event]:
        return [e for e in self._events if e.type == event_type]


def mask_phone(phone: Optional[str]) -> str:
    """Never let a raw phone number into an event payload (audit logs are retained).
    Keep only the last 4 digits for correlation."""
    if not phone:
        return "unknown"
    digits = "".join(c for c in phone if c.isdigit())
    return f"***{digits[-4:]}" if len(digits) >= 4 else "***"


class EventEmitter:
    """Stamps and forwards events for one call. Bound to a `CallSession` so every
    event inherits the correct tenant/campaign/lead/call/agent correlation ids."""

    def __init__(self, sink: EventSink, session: CallSession) -> None:
        self._sink = sink
        self._session = session

    async def emit(
        self,
        event_type: EventType,
        payload: Optional[dict[str, Any]] = None,
        *,
        severity: Severity = Severity.INFO,
    ) -> None:
        s = self._session
        await self._sink.emit(
            Event(
                event_id=uuid.uuid4().hex,
                type=event_type,
                occurred_at=datetime.now(timezone.utc),
                severity=severity,
                tenant_id=s.tenant_id,
                campaign_id=s.campaign_id,
                lead_id=s.lead_id,
                call_id=s.call_id,
                agent_id=s.agent_id,
                payload=payload or {},
            )
        )
