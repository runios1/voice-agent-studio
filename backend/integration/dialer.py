"""The real orchestrator `Dialer` — delegates each lead to the VoiceRuntime.

The orchestrator must not run the call itself (README boundary); it hands a claimed lead
to a `Dialer.dial(config, campaign, lead)` and gets back the finished `CallSession`. This
implementation:

  1. builds the PER-AGENT tool registry from the campaign's config (enabled tools only),
  2. creates the per-call transport (Retell or mock),
  3. runs the shared `CallEngine` — the exact same turn loop, disclosure step, and event
     emission as the Phase-1 preview, just over a phone transport.

`stdlib` `VoiceRuntimeDialer` holds a single registry; ours builds it per call because the
registry is agent-specific. Same `Dialer` Protocol, so the runner is unchanged.
"""

from __future__ import annotations

from contracts.campaign.model import Campaign, Lead
from contracts.config_schema.schema import AgentConfig
from contracts.voice_runtime.interface import CallSession

from backend.voice_runtime.engine import CallEngine
from backend.voice_runtime.events import EventSink
from backend.integration.dialer_types import TransportFactory
from backend.integration.runtime import ToolStack


class RealDialer:
    """Adapts the real `CallEngine` into the orchestrator's `Dialer` seam."""

    def __init__(
        self,
        engine: CallEngine,
        tool_stack: ToolStack,
        transport_factory: TransportFactory,
        sink: EventSink,
    ) -> None:
        self._engine = engine
        self._tool_stack = tool_stack
        self._transport_factory = transport_factory
        self._sink = sink

    async def dial(self, config: AgentConfig, campaign: Campaign, lead: Lead) -> CallSession:
        registry = self._tool_stack.registry_for(config, self._sink)
        transport = self._transport_factory.create(lead)
        return await self._engine.run_call(config, lead, transport, registry)
