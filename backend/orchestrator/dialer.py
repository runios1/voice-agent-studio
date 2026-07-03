"""The seam to the VoiceRuntime (P2-1) — the orchestrator delegates the call, never runs it.

Per the README boundary, the orchestrator MUST NOT run the call itself. It hands a
claimed lead to a `Dialer`, which returns the finished `CallSession` (outcome + ids).

`VoiceRuntimeDialer` is the real wiring: it adapts the frozen `VoiceRuntime.run_call`
(config, lead, transport, registry) into the runner's simpler `dial(config, campaign,
lead)` call. The transport is provider-specific (Retell/LiveKit), so it comes from an
injected `TransportFactory` that P2-1 provides at integration; the registry comes from
P2-3. Both are contracts, mocked until merged.

Idempotency note: the runner stamps `lead.last_call_id` before dialing, so a
conformant runtime uses it as the call's idempotency key and returns the recorded
outcome on a resume instead of re-dialing (P2-D2). `last_call_id` is already on the
frozen `Lead`, so this needs no contract change.
"""

from __future__ import annotations

from typing import Protocol

from contracts.campaign.model import Campaign, Lead
from contracts.config_schema.schema import AgentConfig
from contracts.tool_registry.interface import ToolRegistry
from contracts.voice_runtime.interface import CallSession, CallTransport, VoiceRuntime


class TransportFactory(Protocol):
    """Builds the per-call transport (phone medium). Owned by P2-1 in production."""

    def create(self, lead: Lead) -> CallTransport: ...


class Dialer(Protocol):
    """The one call the runner makes to place a dial and get its outcome."""

    async def dial(self, config: AgentConfig, campaign: Campaign, lead: Lead) -> CallSession: ...


class VoiceRuntimeDialer:
    """Adapts a frozen VoiceRuntime into the runner's Dialer. This is the code path
    the integrator keeps; only the injected runtime/transport/registry become real."""

    def __init__(
        self,
        runtime: VoiceRuntime,
        transport_factory: TransportFactory,
        registry: ToolRegistry,
    ):
        self._runtime = runtime
        self._transport_factory = transport_factory
        self._registry = registry

    async def dial(self, config: AgentConfig, campaign: Campaign, lead: Lead) -> CallSession:
        transport = self._transport_factory.create(lead)
        return await self._runtime.run_call(config, lead, transport, self._registry)
