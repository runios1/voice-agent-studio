"""The authorized envelope may only be equal-or-stricter than the locked guardrails."""

from __future__ import annotations

import pytest

from contracts.campaign.model import GuardrailEnvelope
from backend.orchestrator.envelope import clamp_envelope, validate_envelope
from backend.orchestrator.errors import EnvelopeViolation
from backend.orchestrator.tests.conftest import make_config


def test_clamp_narrows_calling_window_to_locked():
    config = make_config()  # locked 8–20
    env = GuardrailEnvelope(calling_start_hour_local=6, calling_end_hour_local=23)
    safe = clamp_envelope(env, config)
    assert safe.calling_start_hour_local == 8
    assert safe.calling_end_hour_local == 20


def test_clamp_keeps_a_stricter_user_window():
    config = make_config()
    env = GuardrailEnvelope(calling_start_hour_local=10, calling_end_hour_local=17)
    safe = clamp_envelope(env, config)
    assert (safe.calling_start_hour_local, safe.calling_end_hour_local) == (10, 17)


def test_clamp_caps_attempts_at_locked_max():
    config = make_config()  # max_call_attempts default 3
    env = GuardrailEnvelope(max_attempts_per_lead=99)
    assert clamp_envelope(env, config).max_attempts_per_lead == 3


def test_clamp_degenerate_window_falls_back_to_locked():
    config = make_config()
    # A window entirely outside the locked one collapses; we clamp to the locked span
    # rather than produce an inverted start > end.
    env = GuardrailEnvelope(calling_start_hour_local=21, calling_end_hour_local=23)
    safe = clamp_envelope(env, config)
    assert (safe.calling_start_hour_local, safe.calling_end_hour_local) == (8, 20)


def test_validate_rejects_a_widened_window():
    config = make_config()
    with pytest.raises(EnvelopeViolation):
        validate_envelope(GuardrailEnvelope(calling_start_hour_local=5), config)
    with pytest.raises(EnvelopeViolation):
        validate_envelope(GuardrailEnvelope(calling_end_hour_local=22), config)
    with pytest.raises(EnvelopeViolation):
        validate_envelope(GuardrailEnvelope(max_attempts_per_lead=10), config)


def test_validate_accepts_an_equal_or_stricter_envelope():
    config = make_config()
    validate_envelope(GuardrailEnvelope(calling_start_hour_local=9, calling_end_hour_local=18), config)
    validate_envelope(GuardrailEnvelope(max_attempts_per_lead=3), config)  # equal is allowed
