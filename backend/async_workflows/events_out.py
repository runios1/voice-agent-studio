"""Emitting to the event stream (P2-5).

This stream is a CONSUMER of `lead.outcome` and a PRODUCER of `followup.scheduled`
and `tool.invoked` (README boundary). Everything we do lands on the same append-only
stream that feeds the dashboard, auto-pause, and the audit log — a post-call email
is as auditable as the call that triggered it.

`EventSink` is the write side of P2-5's bus; we depend only on the frozen `Event`
envelope, never on P2-5's transport. The builders below stamp correlation ids from
the trigger so every emitted event is sliceable by tenant/campaign/lead/call with
no join (the envelope's whole purpose).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional, Protocol

from contracts.events.schema import Event, EventType, Severity

from .models import Trigger


class EventSink(Protocol):
    async def emit(self, event: Event) -> None: ...


def _event(
    event_type: EventType,
    trigger: Trigger,
    occurred_at: datetime,
    payload: dict[str, Any],
    *,
    severity: Severity = Severity.INFO,
    call_id: Optional[str] = None,
) -> Event:
    return Event(
        event_id=str(uuid.uuid4()),
        type=event_type,
        occurred_at=occurred_at,
        severity=severity,
        tenant_id=trigger.tenant_id,
        campaign_id=trigger.campaign_id,
        lead_id=trigger.lead_id,
        call_id=call_id or trigger.call_id,
        agent_id=trigger.agent_id,
        payload=payload,
    )


def tool_invoked_event(
    trigger: Trigger,
    occurred_at: datetime,
    *,
    tool: str,
    args: dict[str, Any],
    result: dict[str, Any],
    workflow: str,
) -> Event:
    """One POST_CALL tool ran. `origin_event_id` back-links to the outcome that
    triggered the workflow so the audit trail reads call -> outcome -> automation."""
    return _event(
        EventType.TOOL_INVOKED,
        trigger,
        occurred_at,
        {
            "tool": tool,
            "timing": "post_call",
            "workflow": workflow,
            "args": args,
            "result": result,
            "origin_event_id": trigger.run_id,
        },
    )


def followup_scheduled_event(
    trigger: Trigger,
    occurred_at: datetime,
    *,
    workflow: str,
    scheduled_action_id: str,
    run_at: datetime,
) -> Event:
    """A follow-up touch was deferred. `run_at` lets the dashboard show what's pending
    and the audit log prove the cadence honored the configured delay."""
    return _event(
        EventType.FOLLOWUP_SCHEDULED,
        trigger,
        occurred_at,
        {
            "workflow": workflow,
            "scheduled_action_id": scheduled_action_id,
            "run_at": run_at.isoformat(),
            "origin_event_id": trigger.run_id,
        },
    )
