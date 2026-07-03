"""Emitting lifecycle Events (P2-D5) — the orchestrator's half of the event stream.

The orchestrator emits the **campaign/lead** lifecycle events; the *call* lifecycle
events (`call.started`, `disclosure.spoken`, …) are the VoiceRuntime's to emit
(P2-1), and trip patterns are P2-6's to detect — we only feed the stream.

`EventSink` is the seam to the event backbone (P2-5). It is deliberately tiny —
append one immutable Event — because the log is append-only (the compliance record,
P2-D5). `InMemoryEventSink` backs tests/CI; at integration the real P2-5 sink is
injected with no other change.

Event ids are generated here so an emit is a single, self-contained append. The
builders stamp correlation ids (tenant always present, D-security) from the
Campaign/Lead so every consumer can slice without a join.
"""

from __future__ import annotations

import uuid
from typing import Optional, Protocol

from contracts.campaign.model import Campaign, Lead
from contracts.events.schema import Event, EventType, Severity
from backend.orchestrator.clock import Clock


class EventSink(Protocol):
    """Append one Event to the immutable stream. Async to match a real bus/DB sink."""

    async def emit(self, event: Event) -> None: ...


class InMemoryEventSink:
    """Reference sink for tests/CI. Append-only; never mutates or drops."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    async def emit(self, event: Event) -> None:
        self.events.append(event)

    # --- test conveniences (read-only) ---------------------------------------
    def of_type(self, t: EventType) -> list[Event]:
        return [e for e in self.events if e.type == t]

    def types(self) -> list[EventType]:
        return [e.type for e in self.events]


def _new_id() -> str:
    return f"evt_{uuid.uuid4().hex[:16]}"


def campaign_event(
    campaign: Campaign,
    type: EventType,
    clock: Clock,
    severity: Severity = Severity.INFO,
    payload: Optional[dict] = None,
) -> Event:
    return Event(
        event_id=_new_id(),
        type=type,
        occurred_at=clock.now(),
        severity=severity,
        tenant_id=campaign.tenant_id,
        campaign_id=campaign.id,
        agent_id=campaign.agent_id,
        payload=payload or {},
    )


def lead_event(
    campaign: Campaign,
    lead: Lead,
    type: EventType,
    clock: Clock,
    severity: Severity = Severity.INFO,
    payload: Optional[dict] = None,
) -> Event:
    return Event(
        event_id=_new_id(),
        type=type,
        occurred_at=clock.now(),
        severity=severity,
        tenant_id=lead.tenant_id,
        campaign_id=campaign.id,
        lead_id=lead.id,
        call_id=lead.last_call_id,
        agent_id=campaign.agent_id,
        payload=payload or {},
    )
