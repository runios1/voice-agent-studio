"""
FROZEN CONTRACT (Phase 2) — Campaign + lead-lifecycle model
===========================================================

The state the campaign orchestrator (P2-2) persists in Postgres and the dashboard
(P2-7) reads. Bounded autonomy (P2-D1): a human authorizes a Campaign (agent + leads
+ schedule + guardrail envelope); the agent runs it unsupervised within that
envelope, with the kill switch (P2-D3) able to flip campaign state at any time.

Per-lead state MUST be persisted (not held in worker memory) so a crash resumes
from the DB with no double-dial (P2-D2). `attempts` + `next_action_at` are how
retries/backoff and calling-hours windows are honored durably.

This is a STUB defining shape; the queue/worker machinery lives in P2-2.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CampaignState(str, Enum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"        # manual pause, global emergency stop, OR auto-pause (P2-6)
    COMPLETED = "completed"


class LeadState(str, Enum):
    QUEUED = "queued"
    DIALING = "dialing"
    IN_CALL = "in_call"
    OUTCOME = "outcome"        # call finished; outcome recorded
    FOLLOW_UP = "follow_up"    # awaiting a scheduled follow-up action
    RETRY = "retry"            # no-answer/busy; will re-dial after backoff
    DONE = "done"              # terminal: booked, disqualified, opted-out, exhausted


class GuardrailEnvelope(BaseModel):
    """The bounded-autonomy envelope a human authorizes (P2-D1). These sit WITHIN the
    platform's locked compliance guardrails (they can only be equal-or-stricter — the
    orchestrator enforces that they never widen a locked bound like calling hours)."""

    max_concurrent_calls: int = 5
    calls_per_minute: int = 10
    max_attempts_per_lead: int = 3          # ties to per-lead `attempts`
    # local calling window; clamped by the config's LOCKED calling_hours.
    calling_start_hour_local: int = 8
    calling_end_hour_local: int = 20


class Lead(BaseModel):
    id: str
    campaign_id: str
    tenant_id: str
    phone: str
    display_name: Optional[str] = None
    state: LeadState = LeadState.QUEUED
    attempts: int = 0
    next_action_at: Optional[datetime] = None   # when the worker may next act (backoff/window)
    outcome: Optional[str] = None
    last_call_id: Optional[str] = None


class Campaign(BaseModel):
    id: str
    tenant_id: str
    agent_id: str                                # which built AgentConfig runs this campaign
    name: str = "Untitled campaign"
    state: CampaignState = CampaignState.DRAFT
    envelope: GuardrailEnvelope = Field(default_factory=GuardrailEnvelope)
    authorized_by: Optional[str] = None          # the human who launched it (P2-D1)
    authorized_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    # auto-pause bookkeeping (P2-6): why/when it self-paused, surfaced on the dashboard.
    autopause_reason: Optional[str] = None
