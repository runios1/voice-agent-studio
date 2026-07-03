"""Per-`EventType` payload schemas — the half the frozen contract hands to P2-5.

`contracts/events/schema.py` keeps `Event.payload` a **generic dict on purpose** so
the envelope stays stable as payloads evolve. P2-5 owns the per-type shape and
validates it at the **emit boundary** (constrain -> validate -> recover, D-reliability):
a malformed payload is rejected before it is ever persisted, so the append-only log
never contains a garbage event.

Design choices (grill: "payload-model registry, validate on emit"):
  * One pydantic model per `EventType`, collected in `PAYLOAD_MODELS`.
  * `extra="allow"` — emitters MAY attach extra fields (payloads evolve without a
    contract bump); the KNOWN fields are still typed and required-checked, which is
    what gives validation teeth for the compliance-critical events.
  * Compliance-critical events (`disclosure.spoken`, `guardrail.tripped`,
    `lead.outcome`, `slot.booked`) have REQUIRED fields — those are the audit proof,
    so an emitter that forgets them fails loudly at emit rather than logging a
    hollow record.

Validation returns a normalized dict (the model re-dumped) that is stored back into
the generic `payload` field of the envelope, so the persisted event still matches
the frozen contract exactly.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from contracts.events.schema import EventType


class _Payload(BaseModel):
    """Base for every payload model: validate known fields, allow forward-compatible
    extras. `strict=False` so ints/strs coerce the way pydantic does elsewhere here."""

    model_config = ConfigDict(extra="allow")


# --- call lifecycle ---------------------------------------------------------
class CallStartedPayload(_Payload):
    to_number: Optional[str] = None
    from_number: Optional[str] = None
    direction: str = "outbound"


class CallEndedPayload(_Payload):
    duration_seconds: Optional[float] = None
    ended_reason: Optional[str] = None  # completed / no_answer / voicemail / hangup / error


class DisclosureSpokenPayload(_Payload):
    # Compliance-critical: the immutable record that AI disclosure was made.
    disclosed: bool = True
    text: str  # REQUIRED — the exact disclosure said, kept for audit.


class CallEscalatedPayload(_Payload):
    reason: str  # REQUIRED — lead_requested_human / low_confidence / guardrail_edge
    transferred_to: Optional[str] = None


# --- outcomes / actions -----------------------------------------------------
class SlotBookedPayload(_Payload):
    slot_start: str  # REQUIRED — ISO datetime string of the booked slot.
    slot_end: Optional[str] = None
    calendar_id: Optional[str] = None


class ToolInvokedPayload(_Payload):
    tool_name: str  # REQUIRED — which registry tool ran (P2-3).
    params: dict[str, Any] = {}
    result_status: Optional[str] = None  # ok / error / denied


class LeadOutcome(str, Enum):
    QUALIFIED = "qualified"
    NOT_QUALIFIED = "not_qualified"
    NO_ANSWER = "no_answer"
    VOICEMAIL = "voicemail"
    CALLBACK_REQUESTED = "callback_requested"
    DO_NOT_CALL = "do_not_call"
    ERROR = "error"


class LeadOutcomePayload(_Payload):
    outcome: LeadOutcome  # REQUIRED — the qualification result.
    note: Optional[str] = None


class FollowupScheduledPayload(_Payload):
    scheduled_for: str  # REQUIRED — ISO datetime the follow-up is due.
    channel: Optional[str] = None  # email / sms / call


# --- safety / control -------------------------------------------------------
class GuardrailTrippedPayload(_Payload):
    # Feeds auto-pause (P2-6): the `guardrail` name is what P2-6 counts in a window.
    guardrail: str  # REQUIRED — e.g. dnc / calling_hours / out_of_range_promise / disclosure_missing
    detail: Optional[str] = None


class CampaignStartedPayload(_Payload):
    lead_count: Optional[int] = None


class CampaignPausedPayload(_Payload):
    # Manual pause OR global emergency stop (P2-D3). `scope` distinguishes them.
    scope: str = "campaign"  # campaign / global
    reason: Optional[str] = None
    actor: Optional[str] = None


class CampaignAutopausedPayload(_Payload):
    # Emitted by P2-6 when a trip pattern fires. `trigger` names the rule.
    trigger: str  # REQUIRED — which detection rule tripped.
    count: Optional[int] = None
    window_seconds: Optional[int] = None


class CampaignResumedPayload(_Payload):
    actor: Optional[str] = None


PAYLOAD_MODELS: dict[EventType, type[_Payload]] = {
    EventType.CALL_STARTED: CallStartedPayload,
    EventType.CALL_ENDED: CallEndedPayload,
    EventType.DISCLOSURE_SPOKEN: DisclosureSpokenPayload,
    EventType.CALL_ESCALATED: CallEscalatedPayload,
    EventType.SLOT_BOOKED: SlotBookedPayload,
    EventType.TOOL_INVOKED: ToolInvokedPayload,
    EventType.LEAD_OUTCOME: LeadOutcomePayload,
    EventType.FOLLOWUP_SCHEDULED: FollowupScheduledPayload,
    EventType.GUARDRAIL_TRIPPED: GuardrailTrippedPayload,
    EventType.CAMPAIGN_STARTED: CampaignStartedPayload,
    EventType.CAMPAIGN_PAUSED: CampaignPausedPayload,
    EventType.CAMPAIGN_AUTOPAUSED: CampaignAutopausedPayload,
    EventType.CAMPAIGN_RESUMED: CampaignResumedPayload,
}

# Every EventType MUST have a payload model — a missing one means an emitter could
# write an unvalidated event. Enforced at import so the gap is impossible to ship.
_missing = set(EventType) - set(PAYLOAD_MODELS)
if _missing:  # pragma: no cover - guards against a future enum addition
    raise RuntimeError(f"payload model missing for event types: {_missing}")


def validate_payload(event_type: EventType, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate `payload` against its per-type model and return the normalized dict.

    Raises `pydantic.ValidationError` on a bad/missing required field — the caller
    (`EventService.emit`) translates that into a typed `EventValidationError` so no
    stack trace escapes and nothing malformed is persisted.
    """
    model = PAYLOAD_MODELS[event_type]
    return model.model_validate(payload).model_dump(mode="json")
