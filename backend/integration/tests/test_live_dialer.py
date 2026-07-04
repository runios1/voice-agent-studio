"""LiveDialer against fakes — no real Live session, no Twilio, no call."""

from __future__ import annotations

from datetime import datetime, timezone

from contracts.campaign.model import Campaign, Lead
from contracts.live_agent.interface import LiveOutcome
from contracts.voice_runtime.interface import CallOutcome

from backend.integration.live_dialer import LiveDialer, _to_call_outcome
from backend.live_agent.events import CollectingEventSink
from backend.live_agent.phone_transport import PhoneNotAnswered
from backend.runtime_loop.fixtures import sample_ready_config

_NOW = datetime.now(timezone.utc)
CAMPAIGN = Campaign(id="c1", tenant_id="t1", agent_id="a1", created_at=_NOW, updated_at=_NOW)
LEAD = Lead(id="l1", campaign_id="c1", tenant_id="t1", phone="+15551230000")


class FakeSession:
    def __init__(self, outcome=None, raise_=None) -> None:
        self.outcome = outcome
        self.raise_ = raise_
        self.ran = False

    async def run(self, spec, transport, registry, moderator, ctx):
        self.ran = True
        self.ctx = ctx
        if self.raise_:
            raise self.raise_
        return self.outcome


class FakeTransport:
    def __init__(self) -> None:
        self.ended = False

    async def end(self) -> None:
        self.ended = True


class _Factory:
    def __init__(self, transport) -> None:
        self._t = transport
        self.created: list = []

    def create(self, lead):
        self.created.append(lead)
        return self._t


class _Compiler:
    def compile(self, config):
        return object()


class _RegistryBuilder:
    def registry_for(self, config, sink):
        return object()


class _FakeVerifier:
    """Records the gate call and returns a preset verified/not-verified answer."""

    def __init__(self, verified: bool) -> None:
        self._verified = verified
        self.waited: list = []

    async def verify(self, phone, *, friendly_name=None):
        return "123456"

    async def wait_until_verified(self, phone, *, timeout=None):
        self.waited.append(phone)
        return self._verified


def _dialer(session, transport, verifier=None):
    return LiveDialer(
        compiler=_Compiler(),
        registry_builder=_RegistryBuilder(),
        sink=CollectingEventSink(),
        session_factory=lambda: session,
        moderator_factory=lambda: object(),
        transport_factory=_Factory(transport),
        verifier=verifier,
    )


async def test_dial_runs_the_live_session_and_returns_a_mapped_callsession():
    session = FakeSession(outcome=LiveOutcome.BOOKED)
    dialer = _dialer(session, FakeTransport())
    config = sample_ready_config()

    cs = await dialer.dial(config, CAMPAIGN, LEAD)

    assert session.ran
    assert cs.outcome == CallOutcome.BOOKED
    assert cs.tenant_id == "t1" and cs.campaign_id == "c1" and cs.lead_id == "l1"
    assert cs.agent_id == config.meta.id
    # the session got the correct correlation context
    assert session.ctx.tenant_id == "t1" and session.ctx.lead_id == "l1"


async def test_no_answer_maps_to_no_answer_and_hangs_up_the_ringing_leg():
    transport = FakeTransport()
    session = FakeSession(raise_=PhoneNotAnswered("no answer"))
    dialer = _dialer(session, transport)

    cs = await dialer.dial(sample_ready_config(), CAMPAIGN, LEAD)

    assert cs.outcome == CallOutcome.NO_ANSWER
    assert transport.ended  # we hung up the leg Twilio was still ringing


async def test_gate_waits_for_verification_then_dials():
    verifier = _FakeVerifier(verified=True)
    session = FakeSession(outcome=LiveOutcome.BOOKED)
    dialer = _dialer(session, FakeTransport(), verifier=verifier)

    cs = await dialer.dial(sample_ready_config(), CAMPAIGN, LEAD)

    assert verifier.waited == [LEAD.phone]  # it gated on this lead's number
    assert session.ran  # verified -> the call was placed
    assert cs.outcome == CallOutcome.BOOKED


async def test_gate_skips_the_call_when_never_verified():
    verifier = _FakeVerifier(verified=False)
    session = FakeSession(outcome=LiveOutcome.BOOKED)
    dialer = _dialer(session, FakeTransport(), verifier=verifier)

    cs = await dialer.dial(sample_ready_config(), CAMPAIGN, LEAD)

    assert verifier.waited == [LEAD.phone]
    assert not session.ran  # unverified -> no call placed
    assert cs.outcome == CallOutcome.NO_ANSWER
    assert cs.lead_id == "l1" and cs.disclosed is False


def test_outcome_mapping():
    assert _to_call_outcome(LiveOutcome.QUALIFIED) == CallOutcome.QUALIFIED
    assert _to_call_outcome(LiveOutcome.NOT_QUALIFIED) == CallOutcome.NOT_QUALIFIED
    assert _to_call_outcome(LiveOutcome.OPTED_OUT) == CallOutcome.OPTED_OUT
    assert _to_call_outcome(LiveOutcome.BOOKED) == CallOutcome.BOOKED
    assert _to_call_outcome(LiveOutcome.NO_ANSWER) == CallOutcome.NO_ANSWER
    assert _to_call_outcome(LiveOutcome.FAILED) == CallOutcome.FAILED
    assert _to_call_outcome(LiveOutcome.ENDED) == CallOutcome.NO_ANSWER  # no CallOutcome.ENDED
