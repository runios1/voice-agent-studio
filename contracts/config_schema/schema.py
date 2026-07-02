"""
FROZEN CONTRACT — Agent Config Schema (SDR vertical, v1)
========================================================

This module is THE central contract of the product. It is the single source of
truth that (per the locked design):

  1. constrains model generation   (builder loop emits patches against it)
  2. drives server-side validation (config gate validates every mutation against it)
  3. renders the Agent panel        (frontend reads it to materialize fields live)
  4. is executed at runtime         (runtime loop reads it to behave)

An "agent" is a structured config object with free-text pockets. It is NOT a
prompt blob. See docs/decisions.md (D3).

CHANGING THIS FILE IS A CROSS-CUTTING EVENT. It is on the critical path; every
workstream depends on it. Freeze v1 before fan-out; version deliberately after.

The *control policy* for these fields (which layer owns them, what is locked vs
open, and which are required for "ready") lives in `field_policy.py`, kept
separate from the data on purpose (data vs. policy separation).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Meta
# --------------------------------------------------------------------------- #
class AgentStatus(str, Enum):
    DRAFT = "draft"      # still being built; completeness model not satisfied
    READY = "ready"      # every `required_for_ready` field satisfied -> deployable


class AgentMeta(BaseModel):
    id: str
    owner_user_id: str
    name: str = "Untitled agent"
    status: AgentStatus = AgentStatus.DRAFT
    version: int = 1                       # bumped on every accepted mutation (undo/history)
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# CONVERSATION section  — guardrails here constrain what the agent may SAY.
# (Timing split: this is the live, in-call back-and-forth. See D6.)
# --------------------------------------------------------------------------- #
class Persona(BaseModel):
    display_name: Optional[str] = None                 # OPEN
    role: Optional[str] = None                         # OPEN  e.g. "SDR for Acme"
    tone: Optional[str] = None                         # OPEN  free-text, materialized on answer
    style_notes: Optional[str] = None                  # OPEN  free-text pocket


class QualificationCriterion(BaseModel):
    label: str
    question: Optional[str] = None
    disqualifying: bool = False


class Qualification(BaseModel):
    framework: Optional[str] = None                    # DEFAULT e.g. "BANT"
    criteria: list[QualificationCriterion] = Field(default_factory=list)


class Objection(BaseModel):
    trigger: str                                       # what the lead says
    response_guidance: str                             # free-text pocket, OPEN


class Disclosure(BaseModel):
    # ai_disclosure is LOCKED true at the policy layer; enforced in CODE at runtime,
    # not as a prompt line (see D-security). The script is a DEFAULT the user may tune.
    must_disclose_ai: bool = True                      # LOCKED
    disclosure_script: Optional[str] = None            # DEFAULT


class ConversationConfig(BaseModel):
    persona: Persona = Field(default_factory=Persona)
    primary_objective: Optional[str] = None            # DEFAULT e.g. "book a 15-min discovery call"
    qualification: Qualification = Field(default_factory=Qualification)
    objections: list[Objection] = Field(default_factory=list)
    disclosure: Disclosure = Field(default_factory=Disclosure)
    # Extensible catch-all for harmless persona/style detail the builder captures
    # via the four-way triage (see D13). NEVER holds capabilities we don't offer.
    custom_instructions: Optional[str] = None          # OPEN, free-text pocket


# --------------------------------------------------------------------------- #
# AUTOMATION section — guardrails here constrain what the agent may DO.
# (Timing split: fast in-call functions + async post-call orchestration. See D6.)
# Every capability here is a code-owned function; absence of a function == absence
# of the capability (structural enforcement, see D-security).
# --------------------------------------------------------------------------- #
class CalendarAutomation(BaseModel):
    enabled: bool = False                              # OPEN
    calendar_ref: Optional[str] = None                 # OPEN (which connected calendar)
    meeting_length_minutes: int = 30                   # DEFAULT
    # business_hours are enforced in the hold_slot() handler, not the prompt.
    booking_window_days: int = 14                      # DEFAULT


class EmailAutomation(BaseModel):
    enabled: bool = False                              # OPEN
    # LINKS ARE NEVER FREE-COMPOSED BY THE MODEL. Only domains on this allowlist may
    # appear in outbound email; the send_email() handler rejects anything else. (D-security)
    template_ids: list[str] = Field(default_factory=list)  # OPEN (from approved templates)


class FollowUpStep(BaseModel):
    delay_hours: int
    channel: Literal["email"] = "email"                # phase-limited; extend later
    template_id: str


class AutomationConfig(BaseModel):
    calendar: CalendarAutomation = Field(default_factory=CalendarAutomation)
    email: EmailAutomation = Field(default_factory=EmailAutomation)
    follow_up: list[FollowUpStep] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# COMPLIANCE GUARDRAILS — platform-owned, mostly LOCKED. This is the base
# characteristics layer that is YOUR product value (see D7). Shown in the panel
# from the start in a "Set by platform" section (D11). Enforced in CODE.
# --------------------------------------------------------------------------- #
class CallingHours(BaseModel):
    start_hour_local: int = 8                           # LOCKED
    end_hour_local: int = 20                            # LOCKED


class ComplianceGuardrails(BaseModel):
    ai_disclosure_required: bool = True                 # LOCKED
    respect_do_not_call: bool = True                    # LOCKED
    calling_hours: CallingHours = Field(default_factory=CallingHours)  # LOCKED
    allowed_link_domains: list[str] = Field(default_factory=list)      # LOCKED (email allowlist)
    max_call_attempts: int = 3                          # DEFAULT
    forbidden_claims: list[str] = Field(default_factory=list)          # LOCKED (e.g. pricing promises)


# --------------------------------------------------------------------------- #
# The agent
# --------------------------------------------------------------------------- #
class AgentConfig(BaseModel):
    meta: AgentMeta
    guardrails: ComplianceGuardrails = Field(default_factory=ComplianceGuardrails)
    conversation: ConversationConfig = Field(default_factory=ConversationConfig)
    automation: AutomationConfig = Field(default_factory=AutomationConfig)

    # Quarantined items from the four-way triage: things the user asked for that we
    # DON'T offer yet. Captured so the user feels heard, but kept OUT of everything
    # the agent acts on. (See D13.) Never fed to generation or runtime as instructions.
    wishlist: list[str] = Field(default_factory=list)
