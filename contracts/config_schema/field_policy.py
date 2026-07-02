"""
FROZEN CONTRACT — Field control policy
======================================

Separates *who controls a field* and *whether it is locked* from the field data
itself (schema.py). This is the machine-readable form of the two-layer control
model (D4) and the completeness model (D12).

The config gate (backend/config_gate) consults FIELD_POLICY on EVERY mutation,
regardless of source (builder tool-call, manual edit, or a forged API request) —
the gate is the source-agnostic enforcement boundary (D-security). The LLM's
triage is UX politeness; THIS is the security boundary.

The frontend reads FIELD_POLICY to render lock badges and to decide which fields
are manually editable.

`required_for_ready == True` fields together ARE the completeness model the
builder interviews toward (D12). When all are satisfied, meta.status -> READY.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class Mutability(str, Enum):
    LOCKED = "locked"    # platform-set; user cannot change; shown read-only (D11)
    DEFAULT = "default"  # platform-suggested; user MAY override
    OPEN = "open"        # fully user-controlled


class Layer(str, Enum):
    PLATFORM = "platform"  # you, the provider — base characteristics + guardrails
    USER = "user"          # the end user — the details


class FieldPolicy(BaseModel):
    path: str                       # dotted path into AgentConfig, e.g. "conversation.persona.tone"
    owner_layer: Layer
    mutability: Mutability
    required_for_ready: bool = False


# NOTE: this is a v1 starting policy for the SDR vertical. Authoring this map IS a
# core part of the product's value and is the platform provider's job (D12). The
# engine that reads it is vertical-agnostic; swapping this map = a new vertical (D7).
FIELD_POLICY: list[FieldPolicy] = [
    # --- platform guardrails: the base characteristics, mostly LOCKED ---
    FieldPolicy(path="guardrails.ai_disclosure_required",        owner_layer=Layer.PLATFORM, mutability=Mutability.LOCKED),
    FieldPolicy(path="guardrails.respect_do_not_call",           owner_layer=Layer.PLATFORM, mutability=Mutability.LOCKED),
    FieldPolicy(path="guardrails.calling_hours",                 owner_layer=Layer.PLATFORM, mutability=Mutability.LOCKED),
    FieldPolicy(path="guardrails.allowed_link_domains",          owner_layer=Layer.PLATFORM, mutability=Mutability.LOCKED),
    FieldPolicy(path="guardrails.forbidden_claims",              owner_layer=Layer.PLATFORM, mutability=Mutability.LOCKED),
    FieldPolicy(path="guardrails.max_call_attempts",             owner_layer=Layer.PLATFORM, mutability=Mutability.DEFAULT),
    FieldPolicy(path="conversation.disclosure.must_disclose_ai", owner_layer=Layer.PLATFORM, mutability=Mutability.LOCKED),

    # --- platform defaults the user may tune ---
    FieldPolicy(path="conversation.disclosure.disclosure_script", owner_layer=Layer.PLATFORM, mutability=Mutability.DEFAULT),
    FieldPolicy(path="conversation.qualification.framework",      owner_layer=Layer.PLATFORM, mutability=Mutability.DEFAULT),

    # --- user-owned details; the completeness model (required_for_ready) ---
    FieldPolicy(path="conversation.persona.role",          owner_layer=Layer.USER, mutability=Mutability.OPEN,    required_for_ready=True),
    FieldPolicy(path="conversation.persona.tone",          owner_layer=Layer.USER, mutability=Mutability.OPEN,    required_for_ready=True),
    FieldPolicy(path="conversation.primary_objective",     owner_layer=Layer.USER, mutability=Mutability.DEFAULT, required_for_ready=True),
    FieldPolicy(path="conversation.qualification.criteria", owner_layer=Layer.USER, mutability=Mutability.OPEN,   required_for_ready=True),
    FieldPolicy(path="conversation.objections",            owner_layer=Layer.USER, mutability=Mutability.OPEN,    required_for_ready=False),
    FieldPolicy(path="conversation.custom_instructions",   owner_layer=Layer.USER, mutability=Mutability.OPEN,    required_for_ready=False),
    FieldPolicy(path="automation.calendar",                owner_layer=Layer.USER, mutability=Mutability.OPEN,    required_for_ready=False),
    FieldPolicy(path="automation.email",                   owner_layer=Layer.USER, mutability=Mutability.OPEN,    required_for_ready=False),
]
