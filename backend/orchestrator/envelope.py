"""The bounded-autonomy envelope, clamped to the platform's locked guardrails.

P2-D1 authorizes an agent to run WITHIN a `GuardrailEnvelope` the human sets. That
envelope may only ever be **equal-or-stricter** than the config's LOCKED compliance
guardrails (`schema.ComplianceGuardrails`) — a user cannot widen calling hours or
raise the attempt cap past what the platform locked (D4/D-security). Enforcement is
in code here, at authorize time; it never trusts the envelope as given.

Two postures, both provided:
  * `clamp_envelope` — silently tighten to the intersection (the default; the user
    asked for a wider window, they get the legal subset). Returns the safe envelope.
  * `validate_envelope` — raise `EnvelopeViolation` if the envelope widens a locked
    bound (used when we'd rather reject a forged/over-broad request than tighten it).
"""

from __future__ import annotations

from contracts.campaign.model import GuardrailEnvelope
from contracts.config_schema.schema import AgentConfig
from backend.orchestrator.errors import EnvelopeViolation


def clamp_envelope(envelope: GuardrailEnvelope, config: AgentConfig) -> GuardrailEnvelope:
    """Return a copy of `envelope` tightened to fit inside the locked guardrails.

    - calling window narrows to the intersection with LOCKED calling_hours,
    - `max_attempts_per_lead` is capped at the config's `max_call_attempts`.
    A tighter user value is always preserved; only over-broad values are pulled in.
    """
    locked = config.guardrails
    ch = locked.calling_hours

    start = max(envelope.calling_start_hour_local, ch.start_hour_local)
    end = min(envelope.calling_end_hour_local, ch.end_hour_local)
    # A degenerate intersection (user window fully outside the locked one) collapses
    # to an empty window; clamp to the locked window rather than invert start > end.
    if start >= end:
        start, end = ch.start_hour_local, ch.end_hour_local

    return envelope.model_copy(
        update={
            "calling_start_hour_local": start,
            "calling_end_hour_local": end,
            "max_attempts_per_lead": min(
                envelope.max_attempts_per_lead, locked.max_call_attempts
            ),
        }
    )


def validate_envelope(envelope: GuardrailEnvelope, config: AgentConfig) -> None:
    """Raise EnvelopeViolation if the envelope is broader than the locked guardrails."""
    ch = config.guardrails.calling_hours
    if envelope.calling_start_hour_local < ch.start_hour_local:
        raise EnvelopeViolation(
            f"calling_start_hour_local {envelope.calling_start_hour_local} is earlier than "
            f"the locked {ch.start_hour_local}."
        )
    if envelope.calling_end_hour_local > ch.end_hour_local:
        raise EnvelopeViolation(
            f"calling_end_hour_local {envelope.calling_end_hour_local} is later than "
            f"the locked {ch.end_hour_local}."
        )
    if envelope.max_attempts_per_lead > config.guardrails.max_call_attempts:
        raise EnvelopeViolation(
            f"max_attempts_per_lead {envelope.max_attempts_per_lead} exceeds the locked "
            f"max_call_attempts {config.guardrails.max_call_attempts}."
        )
