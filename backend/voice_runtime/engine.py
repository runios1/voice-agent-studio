"""CallEngine — the Phase-2 `VoiceRuntime`.

This is Phase 1's `RuntimeEngine` generalized to voice, NOT rewritten (the workstream
boundary): it IMPORTS and reuses the three durable parts unchanged —

  * `compile_system_prompt`      (deterministic prompt composition, guardrails first)
  * `must_disclose` / `disclosure_line`  (the code-emitted AI-disclosure hard step)
  * the "capability == an enabled function" rule (now sourced from the tool registry)

— and swaps only the TRANSPORT (text tokens -> whole utterances over a voice leg) and
the model path (`stream()` -> `complete()`, which surfaces `tool_calls` so IN_CALL
functions can execute live). Every lifecycle point emits a typed Event (P2-D5).

Turn loop, per call:
  start transport -> CALL_STARTED
  agent opening turn (disclosure line code-emitted as the prefix -> DISCLOSURE_SPOKEN)
  for each lead utterance from the transport:
      opt-out?  -> honor immediately (OPTED_OUT), acknowledge, end        [DNC lock]
      human?    -> escalate (warm transfer, TRANSFERRED), end             [P2-D6]
      else      -> agent turn: model may call IN_CALL tools (TOOL_INVOKED,
                   SLOT_BOOKED on a booking), then speaks
  end transport -> determine outcome -> LEAD_OUTCOME, CALL_ENDED

Guardrails at the tool boundary are the HANDLER's job (P2-3): a handler rejects by
raising; the engine turns that into a GUARDRAIL_TRIPPED event (feeds auto-pause, P2-6)
and feeds the rejection back to the model rather than crashing the call (D-reliability).
"""

from __future__ import annotations

import json
import uuid
from typing import Optional

from contracts.campaign.model import Lead
from contracts.config_schema.schema import AgentConfig
from contracts.events.schema import EventType, Severity
from contracts.model_wrapper.interface import Message, ModelWrapper
from contracts.tool_registry.interface import ToolRegistry
from contracts.voice_runtime.interface import (
    CallOutcome,
    CallSession,
    CallTransport,
    Utterance,
)

from backend.runtime_loop.compiler import compile_system_prompt
from backend.runtime_loop.guardrails import disclosure_line, must_disclose
from backend.voice_runtime.events import EventEmitter, EventSink, mask_phone
from backend.voice_runtime.outcomes import (
    HeuristicOutcomeClassifier,
    OutcomeClassifier,
    detect_human_request,
    detect_opt_out,
)
from backend.voice_runtime.tools import build_tool_defs, context_for

# The safe acknowledgement spoken when a lead opts out. Code-owned (like disclosure),
# so no persona/injection can turn a DNC opt-out into a rebuttal.
OPT_OUT_ACK = (
    "Understood — I'll make sure you're not contacted again. Sorry to bother you, "
    "and have a good day."
)

# Bound on in-call tool round-trips per agent turn, so a misbehaving model can't spin
# the call (D-reliability). After this, the engine stops soliciting tool calls.
MAX_TOOL_HOPS = 4


class CallEngine:
    """A `VoiceRuntime`. Stateless except for the injected sink/classifier and a small
    registry of in-flight transports (so `escalate` can reach the active call's leg
    without widening the frozen `CallSession`). Safe to share one instance across
    concurrent calls — per-call state lives on the `CallSession` and locals."""

    def __init__(
        self,
        wrapper: ModelWrapper,
        sink: EventSink,
        *,
        model_tier: str = "voice",
        classifier: Optional[OutcomeClassifier] = None,
    ) -> None:
        self.wrapper = wrapper
        self.sink = sink
        self.model_tier = model_tier
        self.classifier = classifier or HeuristicOutcomeClassifier()
        # call_id -> transport, for the current in-flight calls (escalate lookup).
        self._active: dict[str, CallTransport] = {}

    # ------------------------------------------------------------------ run --- #
    async def run_call(
        self,
        config: AgentConfig,
        lead: Lead,
        transport: CallTransport,
        registry: ToolRegistry,
    ) -> CallSession:
        session = CallSession(
            call_id=uuid.uuid4().hex,
            tenant_id=lead.tenant_id,
            campaign_id=lead.campaign_id,
            lead_id=lead.id,
            agent_id=config.meta.id,
        )
        emitter = EventEmitter(self.sink, session)
        self._active[session.call_id] = transport
        transcript: list[Utterance] = []
        tools = build_tool_defs(config, registry)

        try:
            await transport.start(lead.phone)
            await emitter.emit(
                EventType.CALL_STARTED,
                {"phone": mask_phone(lead.phone), "lead": lead.display_name},
            )

            # A pre-conversation platform signal (no-answer / voicemail) short-circuits
            # before any turn — there is no one to disclose to.
            forced = getattr(transport, "forced_outcome", None)
            if forced is not None:
                session.outcome = forced
            else:
                # Outbound SDR speaks first: opening turn carries the code-emitted
                # disclosure, then the model's opening.
                await self._agent_turn(
                    config, session, transport, registry, emitter, tools,
                    transcript, opening=True,
                )
                await self._converse(
                    config, session, transport, registry, emitter, tools, transcript,
                )
        finally:
            await transport.end()
            self._active.pop(session.call_id, None)

        if session.outcome is None:
            session.outcome = self.classifier.classify(config, transcript)

        await emitter.emit(EventType.LEAD_OUTCOME, {"outcome": session.outcome.value})
        await emitter.emit(EventType.CALL_ENDED, {"outcome": session.outcome.value})
        return session

    async def _converse(
        self, config, session, transport, registry, emitter, tools, transcript,
    ) -> None:
        """Drive the back-and-forth until the transport's lead stream ends or a
        terminal control condition (opt-out / escalation) stops it."""
        async for utt in transport.receive():
            transcript.append(utt)

            # DNC opt-out — a LOCKED guardrail. Honor immediately, in code: acknowledge
            # and end. Never routed through the model (which a persona could subvert).
            # This is a lead OUTCOME (recorded as OPTED_OUT below), not a guardrail
            # *trip* — the agent did nothing wrong, so it must not inflate P2-6's
            # trip counter; auto-pause can threshold on opted_out outcomes separately.
            if detect_opt_out(utt.text):
                session.outcome = CallOutcome.OPTED_OUT
                await transport.send_agent_utterance(OPT_OUT_ACK)
                transcript.append(Utterance(speaker="agent", text=OPT_OUT_ACK))
                return

            # Explicit request for a human -> warm transfer (P2-D6).
            if detect_human_request(utt.text):
                await self.escalate(session, "lead requested a human")
                return

            await self._agent_turn(
                config, session, transport, registry, emitter, tools, transcript,
                opening=False,
            )

    # --------------------------------------------------------------- a turn --- #
    async def _agent_turn(
        self, config, session, transport, registry, emitter, tools, transcript,
        *, opening: bool,
    ) -> None:
        """Produce and speak one agent utterance. Disclosure (once per call) is a code
        prefix; the model turn may execute IN_CALL tools before it settles on text."""
        parts: list[str] = []

        # --- Hard guardrail step: AI disclosure, once per call, code-emitted. ---
        if not session.disclosed and must_disclose(config):
            line = disclosure_line(config)
            session.disclosed = True
            parts.append(line)
            await emitter.emit(EventType.DISCLOSURE_SPOKEN, {"text": line})

        # Prompt recompiles each turn (a mid-call config edit takes effect), guardrails
        # ordered above persona; `wishlist` never reaches the model.
        system_prompt = compile_system_prompt(config, opening_turn=opening)
        model_messages: list[Message] = [Message(role="system", content=system_prompt)]
        if opening:
            model_messages.append(
                Message(role="user", content="Begin the call now with your opening.")
            )
        else:
            model_messages.extend(_history_messages(transcript))

        text = await self._model_with_tools(
            model_messages, tools, session, registry, emitter,
        )
        if text:
            parts.append(text)

        utterance = " ".join(p for p in parts if p).strip()
        if utterance:
            await transport.send_agent_utterance(utterance)
            transcript.append(Utterance(speaker="agent", text=utterance))

    async def _model_with_tools(
        self, model_messages, tools, session, registry, emitter,
    ) -> str:
        """One model turn that may call IN_CALL tools. Executes each call against the
        registry handler, feeds the result back, and loops (bounded) until the model
        returns text. A handler rejection (guardrail) is caught and fed back, never
        raised into the call."""
        for _ in range(MAX_TOOL_HOPS):
            resp = await self.wrapper.complete(
                model_messages, tools=tools, model_tier=self.model_tier
            )
            if not resp.tool_calls:
                return resp.text or ""

            for call in resp.tool_calls:
                result = await self._execute_tool(call, session, registry, emitter)
                # Record the call + result so the model can react on the next hop.
                model_messages.append(
                    Message(role="assistant", content=f"[tool_call {call.name} {json.dumps(call.arguments)}]")
                )
                model_messages.append(
                    Message(role="tool", content=json.dumps(result))
                )

        # Exhausted the hop budget without settling on text — ask once for a plain
        # spoken reply rather than looping forever.
        resp = await self.wrapper.complete(model_messages, tools=None, model_tier=self.model_tier)
        return resp.text or ""

    async def _execute_tool(self, call, session, registry, emitter) -> dict:
        """Run one IN_CALL registry tool. Guardrails are enforced inside the handler
        (P2-3); a rejection surfaces as an exception, which becomes a GUARDRAIL_TRIPPED
        event + an error result fed back to the model (so it can recover gracefully)."""
        await emitter.emit(
            EventType.TOOL_INVOKED, {"tool": call.name, "args": call.arguments}
        )
        # The registry OWNS connection resolution (contract: "a handler never picks its
        # own tenant"). A real registry exposes `resolve_context`, which looks up the
        # tenant's own connection for the tool's provider; we prefer it so real handlers
        # (calendar/email) receive `ctx.connection`. A registry without it (bare mock)
        # falls back to the correlation-id-only context. Duck-typed like `transfer`, so
        # the frozen `ToolRegistry` Protocol is untouched.
        resolve = getattr(registry, "resolve_context", None)
        if callable(resolve):
            ctx = resolve(
                call.name,
                session.tenant_id,
                campaign_id=session.campaign_id,
                lead_id=session.lead_id,
            )
        else:
            ctx = context_for(session)
        try:
            handler = registry.handler_for(call.name)
            result = await handler.execute(call.arguments, ctx)
        except Exception as exc:  # handler rejected (guardrail) or failed
            await emitter.emit(
                EventType.GUARDRAIL_TRIPPED,
                {"tool": call.name, "reason": str(exc)},
                severity=Severity.WARNING,
            )
            return {"ok": False, "error": str(exc)}

        # A successful booking is a first-class outcome + event. Keyed on the handler's
        # result convention (`booked: True`), not a hardcoded tool name — the registry
        # names tools after automation blocks ("calendar"), and a booking handler
        # signals success this way. (Integration note for P2-3 in DONE.md.)
        if isinstance(result, dict) and result.get("booked") is True:
            session.outcome = CallOutcome.BOOKED
            await emitter.emit(EventType.SLOT_BOOKED, {"result": result})
        return result

    # ------------------------------------------------------------- escalate --- #
    async def escalate(self, session: CallSession, reason: str) -> None:
        """Warm transfer to a human (P2-D6). Emits `call.escalated`, performs the leg's
        transfer if the transport supports one, and marks the outcome TRANSFERRED. Safe
        to call from the engine (lead asked for a human / guardrail edge) or externally
        by the orchestrator — the active transport is looked up by call_id."""
        emitter = EventEmitter(self.sink, session)
        await emitter.emit(
            EventType.CALL_ESCALATED, {"reason": reason}, severity=Severity.WARNING
        )
        transport = self._active.get(session.call_id)
        transfer = getattr(transport, "transfer", None)
        if transfer is not None:
            await transfer(reason)
        session.outcome = CallOutcome.TRANSFERRED


def _history_messages(transcript: list[Utterance]) -> list[Message]:
    """Map the transport transcript to model messages: lead -> user, agent -> assistant.
    The code-emitted disclosure is folded into the agent's first utterance, so history
    stays a clean agent/lead transcript (matches Phase 1)."""
    role = {"lead": "user", "agent": "assistant"}
    return [Message(role=role[u.speaker], content=u.text) for u in transcript]
