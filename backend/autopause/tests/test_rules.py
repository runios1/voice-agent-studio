"""Each rule in isolation: what trips it, what doesn't."""

from datetime import timedelta

from contracts.events.schema import EventType, Severity

from backend.autopause.config import (
    CriticalGuardrailConfig,
    EscalationSpikeConfig,
    GuardrailTripConfig,
)
from backend.autopause.mocks import _BASE_TIME, make_event
from backend.autopause.rules import (
    CriticalGuardrailRule,
    EscalationSpikeRule,
    GuardrailTripRule,
)
from backend.autopause.signals import Action


def _trip(at=None, severity=Severity.WARNING, **kw):
    return make_event(EventType.GUARDRAIL_TRIPPED, at=at, severity=severity, **kw)


# --- GuardrailTripRule ----------------------------------------------------


def test_guardrail_trip_fires_at_threshold():
    rule = GuardrailTripRule(GuardrailTripConfig(threshold=3, window_seconds=300))
    assert rule.observe(_trip()) is None
    assert rule.observe(_trip(at=_BASE_TIME + timedelta(seconds=1))) is None
    signal = rule.observe(_trip(at=_BASE_TIME + timedelta(seconds=2)))
    assert signal is not None
    assert signal.action is Action.AUTOPAUSE
    assert signal.campaign_id == "camp-1"


def test_guardrail_trip_ignores_slow_trickle_outside_window():
    rule = GuardrailTripRule(GuardrailTripConfig(threshold=3, window_seconds=60))
    # three trips, each ~40s apart — never 3 inside any 60s window.
    assert rule.observe(_trip(at=_BASE_TIME)) is None
    assert rule.observe(_trip(at=_BASE_TIME + timedelta(seconds=40))) is None
    assert rule.observe(_trip(at=_BASE_TIME + timedelta(seconds=80))) is None


def test_guardrail_trip_is_per_campaign():
    rule = GuardrailTripRule(GuardrailTripConfig(threshold=2, window_seconds=300))
    assert rule.observe(_trip(campaign_id="camp-1")) is None
    # different campaign, same tenant — its own counter.
    assert rule.observe(_trip(campaign_id="camp-2")) is None
    assert rule.observe(_trip(campaign_id="camp-1")) is not None


def test_guardrail_trip_ignores_other_event_types():
    rule = GuardrailTripRule(GuardrailTripConfig(threshold=1))
    assert rule.observe(make_event(EventType.CALL_STARTED)) is None


def test_disabled_rule_never_fires():
    rule = GuardrailTripRule(GuardrailTripConfig(enabled=False, threshold=1))
    assert rule.observe(_trip()) is None


# --- CriticalGuardrailRule ------------------------------------------------


def test_critical_guardrail_fires_on_single_critical():
    rule = CriticalGuardrailRule(CriticalGuardrailConfig())
    signal = rule.observe(_trip(severity=Severity.CRITICAL))
    assert signal is not None
    assert signal.action is Action.AUTOPAUSE


def test_critical_guardrail_ignores_non_critical():
    rule = CriticalGuardrailRule(CriticalGuardrailConfig())
    assert rule.observe(_trip(severity=Severity.WARNING)) is None


# --- EscalationSpikeRule --------------------------------------------------


def test_escalation_spike_fires_and_is_escalate_action():
    rule = EscalationSpikeRule(EscalationSpikeConfig(threshold=2, window_seconds=300))
    e = lambda at=None: make_event(EventType.CALL_ESCALATED, at=at)
    assert rule.observe(e()) is None
    signal = rule.observe(e(at=_BASE_TIME + timedelta(seconds=5)))
    assert signal is not None
    assert signal.action is Action.ESCALATE
    assert signal.severity is Severity.WARNING
