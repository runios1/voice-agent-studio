"""Mocks for the not-yet-merged neighbours (P2-1 VoiceRuntime, P2-3 ToolRegistry).

STEP 2 of the workstream template: reach other streams only through frozen contracts,
and MOCK anything not merged. These fakes are deterministic and idempotency-aware so
the orchestrator's own guarantees (no double-dial, crash-resume, kill switch) can be
proven in CI without a real voice platform.

  * `MockVoiceRuntime` — implements the frozen `VoiceRuntime`. Scriptable outcome per
    lead; **idempotent on `lead.last_call_id`** (a repeated call_id returns the
    recorded outcome and is NOT counted as a new dial) — that is what makes a
    crash-resume provably not double-dial. Optionally emits `call.started/ended`.
  * `ScriptedDialer` — a `Dialer` that skips transport/registry plumbing for pure
    state-machine tests. Same idempotency contract; can `hang` a lead (never returns,
    to simulate a call in flight at crash) or `fail` it.
  * `MockToolRegistry` / `MockTransportFactory` — inert stand-ins to exercise the real
    `VoiceRuntimeDialer` wiring end-to-end.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional

from contracts.campaign.model import Campaign, Lead
from contracts.config_schema.schema import AgentConfig
from contracts.events.schema import EventType
from contracts.tool_registry.interface import RegistryTool, Timing, ToolHandler, ToolRegistry
from contracts.voice_runtime.interface import (
    CallOutcome,
    CallSession,
    CallTransport,
    Utterance,
)
from backend.orchestrator.clock import Clock, SystemClock
from backend.orchestrator.events import EventSink, lead_event


# --------------------------------------------------------------------------- #
# Voice runtime (P2-1) mock
# --------------------------------------------------------------------------- #
class MockVoiceRuntime:
    """Fake `VoiceRuntime`. `outcomes` maps lead_id -> CallOutcome (default QUALIFIED).
    A per-lead list is consumed one-per-attempt so retries can differ."""

    def __init__(
        self,
        outcomes: Optional[dict[str, object]] = None,
        default: CallOutcome = CallOutcome.QUALIFIED,
        sink: Optional[EventSink] = None,
        clock: Optional[Clock] = None,
    ):
        self._outcomes = outcomes or {}
        self._default = default
        self._sink = sink
        self._clock = clock or SystemClock()
        # call_id -> completed CallSession (the idempotency ledger).
        self._done: dict[str, CallSession] = {}
        # call_ids that triggered a REAL dial (repeats don't append) — tests assert on this.
        self.dialed: list[str] = []

    def _pick_outcome(self, lead: Lead) -> CallOutcome:
        spec = self._outcomes.get(lead.id, self._default)
        if isinstance(spec, list):
            idx = min(lead.attempts - 1, len(spec) - 1) if lead.attempts > 0 else 0
            return spec[idx] if spec else self._default
        return spec  # type: ignore[return-value]

    async def run_call(
        self,
        config: AgentConfig,
        lead: Lead,
        transport: CallTransport,
        registry: ToolRegistry,
    ) -> CallSession:
        call_id = lead.last_call_id or f"{lead.id}:{lead.attempts}"
        if call_id in self._done:
            return self._done[call_id]  # idempotent replay — no second dial

        self.dialed.append(call_id)
        outcome = self._pick_outcome(lead)
        session = CallSession(
            call_id=call_id,
            tenant_id=lead.tenant_id,
            campaign_id=lead.campaign_id,
            lead_id=lead.id,
            agent_id=config.meta.id,
            disclosed=True,
            outcome=outcome,
        )
        if self._sink is not None:
            # The runtime owns the call.* events (P2-1); emit them so an integration
            # test sees the full trail. Uses a synthetic Campaign for correlation ids.
            camp = Campaign(
                id=lead.campaign_id,
                tenant_id=lead.tenant_id,
                agent_id=config.meta.id,
                created_at=self._clock.now(),
                updated_at=self._clock.now(),
            )
            await self._sink.emit(lead_event(camp, lead, EventType.CALL_STARTED, self._clock))
            await self._sink.emit(
                lead_event(
                    camp, lead, EventType.CALL_ENDED, self._clock,
                    payload={"outcome": outcome.value},
                )
            )
        self._done[call_id] = session
        return session

    async def escalate(self, session: CallSession, reason: str) -> None:  # pragma: no cover
        session.outcome = CallOutcome.TRANSFERRED


# --------------------------------------------------------------------------- #
# Dialer mock (skips transport/registry for state-machine tests)
# --------------------------------------------------------------------------- #
class ScriptedDialer:
    """A `Dialer` with directly-scripted outcomes and fault injection."""

    def __init__(
        self,
        outcomes: Optional[dict[str, object]] = None,
        default: CallOutcome = CallOutcome.QUALIFIED,
        hang_leads: Optional[set[str]] = None,
        fail_leads: Optional[set[str]] = None,
    ):
        self._outcomes = outcomes or {}
        self._default = default
        self._hang = hang_leads or set()
        self._fail = fail_leads or set()
        self._done: dict[str, CallSession] = {}
        self.dialed: list[str] = []
        # Set to a fresh Event each test that wants to release hung calls.
        self.release = asyncio.Event()

    def _pick_outcome(self, lead: Lead) -> CallOutcome:
        spec = self._outcomes.get(lead.id, self._default)
        if isinstance(spec, list):
            idx = min(lead.attempts - 1, len(spec) - 1) if lead.attempts > 0 else 0
            return spec[idx] if spec else self._default
        return spec  # type: ignore[return-value]

    async def dial(self, config: AgentConfig, campaign: Campaign, lead: Lead) -> CallSession:
        call_id = lead.last_call_id or f"{lead.id}:{lead.attempts}"
        if call_id in self._done:
            return self._done[call_id]

        if lead.id in self._hang:
            await self.release.wait()  # block until the test releases (simulate in-flight)

        self.dialed.append(call_id)
        if lead.id in self._fail:
            raise RuntimeError(f"simulated dial failure for {lead.id}")

        outcome = self._pick_outcome(lead)
        session = CallSession(
            call_id=call_id,
            tenant_id=lead.tenant_id,
            campaign_id=campaign.id,
            lead_id=lead.id,
            agent_id=config.meta.id,
            disclosed=True,
            outcome=outcome,
        )
        self._done[call_id] = session
        return session


# --------------------------------------------------------------------------- #
# Tool registry (P2-3) + transport (P2-1) inert stand-ins
# --------------------------------------------------------------------------- #
class MockToolRegistry:
    """Empty ToolRegistry — the orchestrator only passes it through to the runtime."""

    def list_tools(self, timing: Optional[Timing] = None) -> list[RegistryTool]:
        return []

    def get(self, name: str) -> Optional[RegistryTool]:
        return None

    def handler_for(self, name: str) -> ToolHandler:  # pragma: no cover
        raise KeyError(name)


class _NullTransport:
    async def start(self, phone: Optional[str]) -> None: ...
    async def send_agent_utterance(self, text: str) -> None: ...

    async def receive(self) -> AsyncIterator[Utterance]:  # pragma: no cover
        if False:
            yield Utterance(speaker="lead", text="")

    async def end(self) -> None: ...


class MockTransportFactory:
    def create(self, lead: Lead) -> CallTransport:
        return _NullTransport()  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Config source (config_gate at integration) stub
# --------------------------------------------------------------------------- #
class InMemoryConfigSource:
    """Stub `ConfigSource`. At integration, adapt config_gate's tenant-scoped repo
    (`repo.get(agent_id, owner_user_id)`); the tenant check moves there unchanged."""

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], AgentConfig] = {}

    def add(self, tenant_id: str, config: AgentConfig) -> None:
        self._by_key[(config.meta.id, tenant_id)] = config

    def get_config(self, agent_id: str, tenant_id: str) -> Optional[AgentConfig]:
        return self._by_key.get((agent_id, tenant_id))
