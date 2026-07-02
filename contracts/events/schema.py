"""
FROZEN CONTRACT (Phase 2) — Event schema
========================================

THE Phase-2 keystone (P2-D5). Every meaningful action emits one typed event to a
single append-only stream. Four consumers bind to this schema:

  * Dashboard (P2-7)      — subscribes for live views
  * Auto-pause (P2-6)     — detects trip patterns over the stream
  * Audit log             — the persisted stream IS the compliance record
  * Analytics             — aggregates the stream

Because the immutable event log is the **compliance proof** ("this call disclosed
AI / honored the opt-out"), events are APPEND-ONLY. Never mutate or delete.

Changing this file is a cross-cutting event across P2-5/6/7 and every emitter.
Freeze before fan-out; version deliberately after.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class EventType(str, Enum):
    # --- call lifecycle ---
    CALL_STARTED = "call.started"
    CALL_ENDED = "call.ended"
    DISCLOSURE_SPOKEN = "disclosure.spoken"        # compliance-critical
    CALL_ESCALATED = "call.escalated"              # warm transfer to human
    # --- outcomes / actions ---
    SLOT_BOOKED = "slot.booked"
    TOOL_INVOKED = "tool.invoked"
    LEAD_OUTCOME = "lead.outcome"                  # qualified / not / no-answer / etc.
    FOLLOWUP_SCHEDULED = "followup.scheduled"
    # --- safety / control ---
    GUARDRAIL_TRIPPED = "guardrail.tripped"        # feeds auto-pause (P2-6)
    CAMPAIGN_STARTED = "campaign.started"
    CAMPAIGN_PAUSED = "campaign.paused"            # manual pause / global stop
    CAMPAIGN_AUTOPAUSED = "campaign.autopaused"    # tripped by P2-6
    CAMPAIGN_RESUMED = "campaign.resumed"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"      # e.g. a single guardrail trip
    CRITICAL = "critical"    # e.g. an auto-pause / compliance breach


class Event(BaseModel):
    """The append-only envelope. `payload` carries event-type-specific fields
    (validated per-type by P2-5, kept generic here so the contract stays stable as
    payloads evolve). Correlation ids let every consumer slice by tenant / campaign
    / lead / call without a join."""

    event_id: str
    type: EventType
    occurred_at: datetime
    severity: Severity = Severity.INFO

    # correlation — tenant is ALWAYS present (isolation, D-security); the rest are
    # present when the event is scoped to them.
    tenant_id: str
    campaign_id: Optional[str] = None
    lead_id: Optional[str] = None
    call_id: Optional[str] = None
    agent_id: Optional[str] = None

    payload: dict[str, Any] = Field(default_factory=dict)
