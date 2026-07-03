"""AutoPauseEngine end-to-end over synthetic event sequences (the DONE criteria):

  * N guardrail trips in a window → kill switch tripped + `campaign.autopaused` emitted
  * escalation fires on defined conditions
  * cooldown prevents flapping; a resume re-arms
  * tenant/campaign isolation; live stream fan-out
"""

from datetime import timedelta

from contracts.events.schema import EventType, Severity

from backend.autopause.config import EngineConfig, GuardrailTripConfig
from backend.autopause.engine import AutoPauseEngine
from backend.autopause.mocks import (
    InMemoryEventStream,
    RecordingEscalator,
    RecordingKillSwitch,
    RecordingSink,
    _BASE_TIME,
    make_event,
)
from backend.autopause.signals import Action


def _engine(config=None):
    ks, sink, esc = RecordingKillSwitch(), RecordingSink(), RecordingEscalator()
    engine = AutoPauseEngine(
        config=config, kill_switch=ks, event_sink=sink, escalator=esc
    )
    return engine, ks, sink, esc


def _trip(at=None, severity=Severity.WARNING, **kw):
    return make_event(EventType.GUARDRAIL_TRIPPED, at=at, severity=severity, **kw)


# --- core auto-pause ------------------------------------------------------


def test_n_trips_in_window_trips_killswitch_and_emits_autopaused():
    engine, ks, sink, _ = _engine()  # default threshold = 3
    engine.handle(_trip(at=_BASE_TIME))
    engine.handle(_trip(at=_BASE_TIME + timedelta(seconds=1)))
    assert ks.calls == []  # not yet

    acted = engine.handle(_trip(at=_BASE_TIME + timedelta(seconds=2)))

    assert [s.action for s in acted] == [Action.AUTOPAUSE]
    assert ks.calls[0]["campaign_id"] == "camp-1"
    assert ks.calls[0]["tenant_id"] == "tenant-a"
    emitted = sink.of_type(EventType.CAMPAIGN_AUTOPAUSED)
    assert len(emitted) == 1
    assert emitted[0].severity is Severity.CRITICAL
    assert emitted[0].payload["rule"] == "guardrail_trip_threshold"
    assert emitted[0].payload["triggered_by_type"] == "guardrail.tripped"


def test_below_threshold_does_nothing():
    engine, ks, sink, _ = _engine()
    engine.handle(_trip(at=_BASE_TIME))
    engine.handle(_trip(at=_BASE_TIME + timedelta(seconds=1)))
    assert ks.calls == []
    assert sink.events == []


def test_single_critical_trip_pauses_immediately():
    engine, ks, sink, _ = _engine()
    acted = engine.handle(_trip(at=_BASE_TIME, severity=Severity.CRITICAL))
    assert [s.rule for s in acted] == ["critical_guardrail"]
    assert len(ks.calls) == 1
    assert len(sink.of_type(EventType.CAMPAIGN_AUTOPAUSED)) == 1


# --- escalation -----------------------------------------------------------


def test_escalation_spike_pages_human_without_pausing():
    engine, ks, sink, esc = _engine()  # escalation threshold = 3
    for i in range(3):
        engine.handle(
            make_event(EventType.CALL_ESCALATED, at=_BASE_TIME + timedelta(seconds=i))
        )
    assert len(esc.signals) == 1
    assert esc.signals[0].action is Action.ESCALATE
    assert ks.calls == []  # escalation does NOT pause the campaign
    assert sink.events == []


# --- debounce / flapping --------------------------------------------------


def test_cooldown_prevents_reflapping():
    engine, ks, sink, _ = _engine()
    # Trip it (3 events) …
    for i in range(3):
        engine.handle(_trip(at=_BASE_TIME + timedelta(seconds=i)))
    assert len(ks.calls) == 1
    # … keep sending trips; within the 15-min cooldown nothing new fires.
    for i in range(3, 10):
        engine.handle(_trip(at=_BASE_TIME + timedelta(seconds=i)))
    assert len(ks.calls) == 1
    assert len(sink.of_type(EventType.CAMPAIGN_AUTOPAUSED)) == 1


def test_resume_rearms_detection():
    cfg = EngineConfig(guardrail_trip=GuardrailTripConfig(threshold=2, window_seconds=3600))
    engine, ks, _, _ = _engine(cfg)
    engine.handle(_trip(at=_BASE_TIME))
    engine.handle(_trip(at=_BASE_TIME + timedelta(seconds=1)))
    assert len(ks.calls) == 1

    # Operator investigates and resumes → cooldown cleared.
    engine.handle(
        make_event(EventType.CAMPAIGN_RESUMED, at=_BASE_TIME + timedelta(seconds=2))
    )
    # Two fresh trips after resume trip it again.
    engine.handle(_trip(at=_BASE_TIME + timedelta(seconds=3)))
    engine.handle(_trip(at=_BASE_TIME + timedelta(seconds=4)))
    assert len(ks.calls) == 2


def test_cooldown_expiry_allows_retrip():
    cfg = EngineConfig(
        guardrail_trip=GuardrailTripConfig(threshold=1, window_seconds=10),
        autopause_cooldown_seconds=100,
    )
    engine, ks, _, _ = _engine(cfg)
    engine.handle(_trip(at=_BASE_TIME))
    assert len(ks.calls) == 1
    # inside cooldown → suppressed
    engine.handle(_trip(at=_BASE_TIME + timedelta(seconds=50)))
    assert len(ks.calls) == 1
    # past cooldown → fires again
    engine.handle(_trip(at=_BASE_TIME + timedelta(seconds=101)))
    assert len(ks.calls) == 2


# --- isolation ------------------------------------------------------------


def test_tenant_and_campaign_isolation():
    engine, ks, _, _ = _engine()
    # 2 trips on camp-1 (tenant-a), 2 on camp-2 (tenant-b) — neither reaches 3.
    engine.handle(_trip(at=_BASE_TIME, tenant_id="tenant-a", campaign_id="camp-1"))
    engine.handle(_trip(at=_BASE_TIME, tenant_id="tenant-a", campaign_id="camp-1"))
    engine.handle(_trip(at=_BASE_TIME, tenant_id="tenant-b", campaign_id="camp-2"))
    engine.handle(_trip(at=_BASE_TIME, tenant_id="tenant-b", campaign_id="camp-2"))
    assert ks.calls == []


def test_events_without_campaign_id_are_ignored():
    engine, ks, sink, _ = _engine()
    for _ in range(5):
        engine.handle(_trip(campaign_id=None))
    assert ks.calls == []
    assert sink.events == []


# --- live wiring ----------------------------------------------------------


def test_attach_consumes_a_live_stream():
    engine, ks, sink, _ = _engine()
    stream = InMemoryEventStream()
    engine.attach(stream)
    for i in range(3):
        stream.publish(_trip(at=_BASE_TIME + timedelta(seconds=i)))
    assert len(ks.calls) == 1
    assert len(sink.of_type(EventType.CAMPAIGN_AUTOPAUSED)) == 1
