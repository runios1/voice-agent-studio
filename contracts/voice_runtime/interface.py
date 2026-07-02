"""
FROZEN CONTRACT (Phase 2) — Voice-runtime interface
===================================================

Generalizes Phase 1's `backend/runtime_loop/engine.RuntimeEngine`. That engine
already isolates the durable parts (D12): the code-emitted AI-disclosure step, the
least-privilege tool layer, and deterministic prompt composition. Phase 2 swaps the
TRANSPORT (text -> voice/telephony) while keeping those parts identical.

So this contract defines the seam, not a rewrite:
  * `CallTransport` — how utterances move (text I/O in Phase 1; a managed voice
    platform + Gemini Live in Phase 2). Provider-agnostic so Retell -> LiveKit is a
    swap (D9). The existing text engine is the reference `CallTransport`.
  * `VoiceRuntime` — starts/monitors/ends a call for a (config, lead), runs the
    shared turn loop over a transport, executes IN_CALL registry tools, handles warm
    transfer, and emits Events (P2-D5) at each lifecycle point.

STUB: signatures + docstrings are the contract; adapters live in P2-1.
"""

from __future__ import annotations

from enum import Enum
from typing import AsyncIterator, Optional, Protocol

from pydantic import BaseModel

from contracts.campaign.model import Lead
from contracts.config_schema.schema import AgentConfig
from contracts.tool_registry.interface import ToolRegistry


class CallOutcome(str, Enum):
    BOOKED = "booked"
    QUALIFIED = "qualified"
    NOT_QUALIFIED = "not_qualified"
    NO_ANSWER = "no_answer"
    VOICEMAIL = "voicemail"
    OPTED_OUT = "opted_out"          # honor immediately (DNC, locked guardrail)
    TRANSFERRED = "transferred"      # warm transfer to human
    FAILED = "failed"


class Utterance(BaseModel):
    speaker: str        # "agent" | "lead"
    text: str


class CallTransport(Protocol):
    """Moves utterances over some medium. Text (Phase 1) or voice (Phase 2). The
    turn loop is transport-agnostic; barge-in/audio specifics stay behind this."""

    async def start(self, phone: Optional[str]) -> None: ...
    async def send_agent_utterance(self, text: str) -> None: ...
    def receive(self) -> AsyncIterator[Utterance]: ...
    async def end(self) -> None: ...


class CallSession(BaseModel, arbitrary_types_allowed=True):
    """One in-progress call. Carries correlation ids so every emitted Event and every
    ToolContext is scoped correctly (D-security)."""

    call_id: str
    tenant_id: str
    campaign_id: str
    lead_id: str
    agent_id: str
    disclosed: bool = False          # the once-per-call disclosure gate, as in Phase 1
    outcome: Optional[CallOutcome] = None


class VoiceRuntime(Protocol):
    """Runs a bounded-autonomy call. The orchestrator (P2-2) calls `run_call`; the
    runtime owns the shared turn loop (disclosure step, IN_CALL tools via the
    registry, prompt composition) over the injected transport, emits Events, and
    returns the outcome. `escalate` performs the warm transfer (P2-D6)."""

    async def run_call(
        self,
        config: AgentConfig,
        lead: Lead,
        transport: CallTransport,
        registry: ToolRegistry,
    ) -> CallSession: ...

    async def escalate(self, session: CallSession, reason: str) -> None: ...
