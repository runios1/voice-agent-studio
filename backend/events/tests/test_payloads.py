"""Per-type payload validation — the constrain->validate half of D-reliability."""

from __future__ import annotations

import pytest

from contracts.events.schema import EventType
from backend.events.payloads import PAYLOAD_MODELS, validate_payload


def test_every_event_type_has_a_payload_model():
    # If the enum grows a type with no model, an emitter could log unvalidated data.
    assert set(PAYLOAD_MODELS) == set(EventType)


def test_valid_payload_normalizes():
    out = validate_payload(EventType.LEAD_OUTCOME, {"outcome": "qualified", "note": "hot"})
    assert out == {"outcome": "qualified", "note": "hot"}


def test_required_field_missing_raises():
    # guardrail.tripped requires `guardrail` (auto-pause counts it) — omitting fails.
    with pytest.raises(Exception):
        validate_payload(EventType.GUARDRAIL_TRIPPED, {})


def test_disclosure_requires_text():
    with pytest.raises(Exception):
        validate_payload(EventType.DISCLOSURE_SPOKEN, {})
    ok = validate_payload(EventType.DISCLOSURE_SPOKEN, {"text": "This is an AI assistant."})
    assert ok["disclosed"] is True


def test_lead_outcome_enum_enforced():
    with pytest.raises(Exception):
        validate_payload(EventType.LEAD_OUTCOME, {"outcome": "not-a-real-outcome"})


def test_extra_fields_allowed_for_forward_compat():
    out = validate_payload(
        EventType.CALL_STARTED, {"to_number": "+15551234", "future_field": 42}
    )
    assert out["future_field"] == 42
