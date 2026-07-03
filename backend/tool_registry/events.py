"""Event emission seam — MOCK of the P2-5 event bus.

Every tool execution is an action that must land on the single append-only event
stream (P2-D5): `TOOL_INVOKED` always, plus a domain event on success
(`SLOT_BOOKED`) and `GUARDRAIL_TRIPPED` on a code-enforced refusal (which is what
auto-pause, P2-6, watches for). The real bus lives in P2-5 and is not merged yet,
so this workstream depends only on the FROZEN event *schema*
(`contracts/events/schema.py`) and defines a tiny sink Protocol here.

When P2-5 merges, its bus implements this same `emit(Event)` shape (or the
integrator adapts a one-line wrapper) and `InMemoryEventSink` is swapped out. We do
NOT invent event types or payload validation — that is P2-5's job; we only build
`Event` envelopes per the frozen schema and hand them over.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from contracts.events.schema import Event


@runtime_checkable
class EventSink(Protocol):
    """Where built `Event` envelopes go. The real implementation is P2-5's bus."""

    async def emit(self, event: Event) -> None: ...


class InMemoryEventSink:
    """CI/dev sink: records every emitted event so tests can assert on the trail.

    Append-only in spirit (mirrors the real immutable log): `events` is never
    mutated in place beyond appending.
    """

    def __init__(self) -> None:
        self.events: list[Event] = []

    async def emit(self, event: Event) -> None:
        self.events.append(event)

    # --- test/inspection helpers (not part of the sink contract) ---
    def of_type(self, type_) -> list[Event]:
        return [e for e in self.events if e.type == type_]

    def last(self) -> Event:
        return self.events[-1]


class NullEventSink:
    """Drops events. For paths that must run even with no observability wired."""

    async def emit(self, event: Event) -> None:  # noqa: D401 - trivial
        return None
