"""In-memory fakes for the unbuilt collaborators + a synthetic-event factory.

P2-6 is built and tested in isolation, so everything it reaches through a port is
mocked here (README STEP 2: mock anything not yet merged). These are also useful as
reference adapters when the real P2-2 / P2-5 land."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from contracts.events.schema import Event, EventType, Severity

from .signals import Signal

# --- collaborator fakes ---------------------------------------------------


@dataclass
class RecordingKillSwitch:
    """Stands in for P2-2. Records every pause request; `paused` is idempotent."""

    calls: list[dict] = field(default_factory=list)
    paused: set[str] = field(default_factory=set)

    def pause_campaign(self, *, campaign_id: str, tenant_id: str, reason: str) -> None:
        self.calls.append(
            {"campaign_id": campaign_id, "tenant_id": tenant_id, "reason": reason}
        )
        self.paused.add(campaign_id)


@dataclass
class RecordingSink:
    """Stands in for P2-5's emit side. Append-only, like the real log."""

    events: list[Event] = field(default_factory=list)

    def emit(self, event: Event) -> None:
        self.events.append(event)

    def of_type(self, event_type: EventType) -> list[Event]:
        return [e for e in self.events if e.type is event_type]


@dataclass
class RecordingEscalator:
    signals: list[Signal] = field(default_factory=list)

    def escalate(self, signal: Signal) -> None:
        self.signals.append(signal)


class InMemoryEventStream:
    """Minimal live pub/sub matching what `AutoPauseEngine.attach` expects — a
    `subscribe(callback)` + `publish(event)` that fans out synchronously. The real
    P2-5 transport (SSE/WS) gets an adapter with this shape at integration."""

    def __init__(self) -> None:
        self._subscribers: list[Callable[[Event], object]] = []

    def subscribe(self, callback: Callable[[Event], object]) -> None:
        self._subscribers.append(callback)

    def publish(self, event: Event) -> None:
        for callback in self._subscribers:
            callback(event)


# --- synthetic event factory ----------------------------------------------

_BASE_TIME = datetime(2026, 7, 2, 15, 0, 0, tzinfo=timezone.utc)
_ids = itertools.count(1)


def make_event(
    type: EventType,
    *,
    tenant_id: str = "tenant-a",
    campaign_id: Optional[str] = "camp-1",
    at: Optional[datetime] = None,
    severity: Severity = Severity.WARNING,
    lead_id: Optional[str] = None,
    call_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    payload: Optional[dict] = None,
) -> Event:
    """Build a well-formed Event for tests. `at` defaults to a fixed base time so
    windows/cooldowns are deterministic; pass explicit `at` to advance time."""
    return Event(
        event_id=f"evt-{next(_ids)}",
        type=type,
        occurred_at=at or _BASE_TIME,
        severity=severity,
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        lead_id=lead_id,
        call_id=call_id,
        agent_id=agent_id,
        payload=payload or {},
    )
