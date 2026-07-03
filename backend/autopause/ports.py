"""The seams to workstreams this engine depends on but does not own.

P2-6 is read-only over the event stream and does NOT reimplement the pause
mechanism (README boundaries). It reaches its collaborators only through these
narrow ports, which are satisfied by the real workstreams at integration and by
`mocks.py` in isolation:

  * KillSwitch  → P2-2 orchestrator's control API (the one state flag workers honor)
  * EventSink   → P2-5 event stream's emit side (to append `campaign.autopaused`)
  * Escalator   → the human-notification channel (pager/Slack/on-call routing)

Keeping them as Protocols means merging the real orchestrator/event-bus is a
constructor wiring change, not an engine rewrite (D9 spirit)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from contracts.events.schema import Event

from .signals import Signal


@runtime_checkable
class KillSwitch(Protocol):
    """P2-2's kill switch. On auto-pause we flip a campaign to PAUSED: new dials
    stop immediately, in-flight calls finish gracefully (P2-D3). Idempotent —
    pausing an already-paused campaign is a no-op on the orchestrator side."""

    def pause_campaign(self, *, campaign_id: str, tenant_id: str, reason: str) -> None: ...


@runtime_checkable
class EventSink(Protocol):
    """P2-5's emit side. The engine appends `campaign.autopaused` so the dashboard,
    audit log, and analytics all see the same single source of truth."""

    def emit(self, event: Event) -> None: ...


@runtime_checkable
class Escalator(Protocol):
    """Human-in-the-loop notification. Deliberately out-of-band from the event
    enum, which is frozen/closed — the engine does not invent event types."""

    def escalate(self, signal: Signal) -> None: ...
