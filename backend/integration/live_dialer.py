"""The orchestrator `Dialer`, Live-native: a claimed lead becomes a real phone call
driven by the SAME `GeminiLiveAgentSession` the browser preview runs — just over a
`PhoneAudioTransport` (Twilio) instead of the browser WS.

Replaces the old `RealDialer` (text `CallEngine` over Retell) when Twilio is configured,
so campaign calls behave exactly like the preview (audio-native Gemini Live, native
barge-in, in-call tools, streaming moderation, code-guarded events). The orchestrator's
`Dialer` seam is unchanged: `dial(config, campaign, lead) -> CallSession`.
"""

from __future__ import annotations

import logging
import uuid
from typing import Callable, Protocol

from contracts.campaign.model import Campaign, Lead
from contracts.config_schema.schema import AgentConfig
from contracts.live_agent.interface import (
    LiveAgentCompiler,
    LiveAgentSession,
    LiveCallContext,
    LiveOutcome,
    StreamModerator,
)
from contracts.live_agent.interface import AudioTransport
from contracts.voice_runtime.interface import CallOutcome, CallSession

from backend.live_agent.compiler import LiveAgentCompilerImpl
from backend.live_agent.events import EventSink
from backend.live_agent.moderation import build_stream_moderator
from backend.live_agent.phone_transport import (
    CallerIdVerifier,
    NullCallerIdVerifier,
    PhoneNotAnswered,
    build_caller_id_verifier,
    build_phone_transport,
)
from backend.live_agent.session import GeminiLiveAgentSession
from backend.security import build_screener

log = logging.getLogger("voice_agent_studio.live_dialer")


# LiveOutcome -> the orchestrator's CallOutcome. The two enums share every value except
# Live's ENDED (an agent hang-up with no explicit qualification), which is an
# inconclusive call -> NO_ANSWER.
def _to_call_outcome(outcome: LiveOutcome) -> CallOutcome:
    try:
        return CallOutcome(outcome.value)
    except ValueError:
        return CallOutcome.NO_ANSWER


class RegistryBuilder(Protocol):
    def registry_for(self, config: AgentConfig, sink: EventSink): ...


class PhoneTransportFactory(Protocol):
    """Builds the per-call phone transport. Injected so tests never place a real call."""

    def create(self, lead: Lead) -> AudioTransport: ...


class TwilioPhoneTransportFactory:
    """Real per-lead Twilio transport for the campaign dialer."""

    def create(self, lead: Lead) -> AudioTransport:
        return build_phone_transport(lead.phone)


class LiveDialer:
    """Adapts `GeminiLiveAgentSession` into the orchestrator's `Dialer` seam."""

    def __init__(
        self,
        *,
        compiler: LiveAgentCompiler,
        registry_builder: RegistryBuilder,
        sink: EventSink,
        session_factory: Callable[[], LiveAgentSession],
        moderator_factory: Callable[[], StreamModerator],
        transport_factory: PhoneTransportFactory,
        verifier: CallerIdVerifier | None = None,
    ) -> None:
        self._compiler = compiler
        self._registry_builder = registry_builder
        self._sink = sink
        self._session_factory = session_factory
        self._moderator_factory = moderator_factory
        self._transport_factory = transport_factory
        # Trial-account gate: block a lead's call until Twilio has verified its number.
        # The no-op verifier (paid account / disabled) clears instantly, so this is inert
        # on every non-trial path.
        self._verifier = verifier or NullCallerIdVerifier()

    async def dial(self, config: AgentConfig, campaign: Campaign, lead: Lead) -> CallSession:
        ctx = LiveCallContext(
            tenant_id=lead.tenant_id,
            agent_id=config.meta.id,
            campaign_id=campaign.id,
            lead_id=lead.id,
        )

        # Gate on verified-caller-ID (trial demo): verification was kicked off for this
        # lead at authorize time; wait for it to complete before placing the call so a
        # trial account never dials a number Twilio would reject. If it never verifies in
        # time, skip the call as unreachable rather than burn a guaranteed-to-fail attempt.
        if not await self._verifier.wait_until_verified(lead.phone):
            log.warning(
                "lead %s (%s) not verified in time — skipping call (NO_ANSWER)",
                lead.id,
                lead.phone,
            )
            return CallSession(
                call_id=uuid.uuid4().hex,
                tenant_id=lead.tenant_id,
                campaign_id=campaign.id,
                lead_id=lead.id,
                agent_id=config.meta.id,
                disclosed=False,
                outcome=CallOutcome.NO_ANSWER,
            )

        spec = self._compiler.compile(config)
        registry = self._registry_builder.registry_for(config, self._sink)
        transport = self._transport_factory.create(lead)
        session = self._session_factory()
        moderator = self._moderator_factory()

        try:
            outcome = await session.run(spec, transport, registry, moderator, ctx)
        except PhoneNotAnswered:
            # the leg never connected — session.run() raised before its own teardown,
            # so hang up the ringing call ourselves. A normal outcome, not a failure.
            outcome = LiveOutcome.NO_ANSWER
            try:
                await transport.end()
            except Exception:
                pass

        return CallSession(
            call_id=uuid.uuid4().hex,
            tenant_id=lead.tenant_id,
            campaign_id=campaign.id,
            lead_id=lead.id,
            agent_id=config.meta.id,
            disclosed=True,  # the agent is directed to open with it; DISCLOSURE_SPOKEN is the audit record
            outcome=_to_call_outcome(outcome),
        )


def build_live_dialer(
    registry_builder: RegistryBuilder,
    sink: EventSink,
    verifier: CallerIdVerifier | None = None,
) -> LiveDialer:
    """Wire the real Live-native phone dialer (same singletons as the preview). `verifier`
    is the trial-account gate; pass the SAME instance the orchestrator uses to start
    verification so the gate waits on what was kicked off. Defaults to the no-op."""
    screener = build_screener()
    return LiveDialer(
        compiler=LiveAgentCompilerImpl(),
        registry_builder=registry_builder,
        sink=sink,
        session_factory=lambda: GeminiLiveAgentSession(sink),
        moderator_factory=lambda: build_stream_moderator(screener),
        transport_factory=TwilioPhoneTransportFactory(),
        verifier=verifier or build_caller_id_verifier(),
    )
