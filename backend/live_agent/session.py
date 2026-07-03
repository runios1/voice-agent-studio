"""`GeminiLiveAgentSession` — the Live session runtime (P4-2), the core of Phase 4.

Runs ONE conversation per `contracts.live_agent.LiveAgentSession`:

  1. speak the scripted `disclosure_line` in CODE, via the non-conversational
     `Speaker` (speaker.py) — Live has not even connected yet, so no persona/prompt
     could ever skip or paraphrase it (D-security §5).
  2. connect Live with the compiled `LiveAgentSpec` (system instruction, tool
     declarations, in/out transcription) and pump audio both ways. Live owns
     VAD/turn-taking; its own `interrupted` signal (barge-in) is honored by cutting
     whatever the transport is currently playing.
  3. a Live function-call resolves a `ToolContext` (via the registry's
     `resolve_context` if it has one, else the correlation ids alone — the registry
     picks the tenant/connection, never the model) and runs the GUARDED handler;
     the result — never anything the model invented — is returned to Live.
  4. output audio is held for `spec.moderation_buffer_ms` before being handed to the
     transport; the cumulative output transcription is screened every delta via the
     `StreamModerator`. BLOCK cancels whatever is still buffered, cuts what's already
     playing, and steers Live back on guardrail. FLAG is logged but doesn't interrupt
     — the moderator is a net, never the floor (README).
  5. the one turn-loop guardrail that predates Live and is NOT delegated to it: a DNC
     opt-out phrase in the caller's own (transcribed) speech ends the call immediately
     with a fixed, code-spoken acknowledgement — exactly like `CallEngine`'s opt-out
     handling, and for the same reason (a locked compliance guardrail must not depend
     on a persona choosing to honor it).
  6. events go to the injected `EventSink` (audit-log-shaped: disclosure/tool/
     guardrail/booked/outcome — `contracts.events.EventType`) and, separately, to the
     transport's `send_event` (UI-shaped: transcript lines + moderation flags — no
     frozen contract governs this shape, P4-4 owns the wire).

Escalation to a human (warm transfer) is OUT of scope here: `LiveOutcome` has no
TRANSFERRED member and `AudioTransport` has no transfer hook, so there is currently no
contract surface to escalate through — a real warm-transfer needs a CCR, likely
alongside the phone bridge (P4-6). Not silently worked around: simply not attempted.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from contracts.events.schema import EventType, Severity
from contracts.live_agent.interface import (
    AudioTransport,
    LiveAgentSpec,
    LiveCallContext,
    LiveOutcome,
    ModerationVerdict,
    StreamModerator,
)
from contracts.tool_registry.interface import ToolContext, ToolRegistry

from backend.live_agent.events import EventSink, LiveEventEmitter
from backend.live_agent.live_connection import (
    LiveConnection,
    LiveConnector,
    LiveFunctionCall,
    default_live_connector,
)
from backend.live_agent.speaker import Speaker, default_speaker
from backend.voice_runtime.outcomes import detect_opt_out

# Spoken by cutting Live off mid-call (never routed through the model) — same text,
# same rationale as `CallEngine.OPT_OUT_ACK` (a locked DNC guardrail, D-security).
OPT_OUT_ACK = (
    "Understood — I'll make sure you're not contacted again. Sorry to bother you, "
    "and have a good day."
)

# Injected back into Live after a moderation BLOCK to redirect the very next turn.
# Deliberately generic (never echoes the blocked text back into the model's context).
STEER_INSTRUCTION = (
    "(System note: that direction is off-limits. Acknowledge briefly and steer the "
    "conversation back to the call's purpose, within your guardrails.)"
)


@dataclass
class _CallState:
    """Everything the two concurrent pumps (mic-in / Live-out) need to share."""

    outcome: Optional[LiveOutcome] = None
    lead_spoke: bool = False
    blocked: bool = False  # a moderation BLOCK is in effect for the current agent turn
    ended: bool = False  # a hard stop (opt-out) fired; mic pump should stop forwarding
    input_text: str = ""  # caller speech accumulated since the last agent turn started
    output_text: str = ""  # agent speech accumulated since the last turn_complete
    turn_has_output: bool = False
    pending_sends: list[asyncio.Task] = field(default_factory=list)


class GeminiLiveAgentSession:
    """A `LiveAgentSession`. Stateless across calls except for the injected
    sink/connector/speaker — safe to share one instance across concurrent
    conversations (per-call state lives in `_CallState` and locals), mirroring
    `CallEngine`'s posture."""

    def __init__(
        self,
        sink: EventSink,
        *,
        live_connector: Optional[LiveConnector] = None,
        speaker: Optional[Speaker] = None,
    ) -> None:
        self._sink = sink
        self._live_connector = live_connector or default_live_connector
        self._speaker = speaker or default_speaker()

    async def run(
        self,
        spec: LiveAgentSpec,
        transport: AudioTransport,
        registry: ToolRegistry,
        moderator: StreamModerator,
        ctx: LiveCallContext,
    ) -> LiveOutcome:
        call_id = uuid.uuid4().hex
        emitter = LiveEventEmitter(self._sink, ctx, call_id)
        state = _CallState()

        await transport.start()
        await emitter.emit(EventType.CALL_STARTED, {})
        try:
            await self._speak(transport, spec.disclosure_line)
            await transport.send_event({"type": "disclosure", "text": spec.disclosure_line})
            await emitter.emit(EventType.DISCLOSURE_SPOKEN, {"text": spec.disclosure_line})

            async with self._live_connector(spec) as conn:
                await self._drive(conn, spec, transport, registry, moderator, ctx, emitter, state)
        except Exception as exc:  # never let an internal error crash the call visibly
            state.outcome = LiveOutcome.FAILED
            await transport.send_event({"type": "error", "message": str(exc)})
        finally:
            await transport.end()

        outcome = state.outcome or (
            LiveOutcome.QUALIFIED if state.lead_spoke else LiveOutcome.NO_ANSWER
        )
        await emitter.emit(EventType.LEAD_OUTCOME, {"outcome": outcome.value})
        await emitter.emit(EventType.CALL_ENDED, {"outcome": outcome.value})
        return outcome

    # ------------------------------------------------------------ disclosure --- #
    async def _speak(self, transport: AudioTransport, text: str) -> None:
        """Read fixed text aloud via the non-conversational `Speaker`, entirely
        bypassing Live. Used for the opening disclosure and the DNC opt-out ack."""
        async for chunk in self._speaker.speak(text):
            await transport.send_audio(chunk)

    # ------------------------------------------------------------------ drive --- #
    async def _drive(
        self,
        conn: LiveConnection,
        spec: LiveAgentSpec,
        transport: AudioTransport,
        registry: ToolRegistry,
        moderator: StreamModerator,
        ctx: LiveCallContext,
        emitter: LiveEventEmitter,
        state: _CallState,
    ) -> None:
        """Run the mic-in pump and the Live-out pump concurrently until either the
        caller's mic stream ends, Live's stream ends, or a hard stop (opt-out) fires
        — whichever happens first ends the call."""
        mic_task = asyncio.create_task(self._pump_mic(transport, conn, state))
        live_task = asyncio.create_task(
            self._pump_live(conn, spec, transport, registry, moderator, ctx, emitter, state)
        )
        try:
            done, pending = await asyncio.wait(
                {mic_task, live_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
            for t in done:
                if t.cancelled():
                    continue
                exc = t.exception()
                if exc is not None:
                    raise exc
        finally:
            for t in (mic_task, live_task):
                if not t.done():
                    t.cancel()
            # Flush whatever audio was still buffered for the moderation delay when
            # the call ended naturally (a BLOCK/opt-out already cancelled anything it
            # needed to cancel) — trailing agent audio should still reach the caller.
            if state.pending_sends:
                await asyncio.gather(*list(state.pending_sends), return_exceptions=True)

    async def _pump_mic(
        self, transport: AudioTransport, conn: LiveConnection, state: _CallState
    ) -> None:
        async for chunk in transport.recv_audio():
            if state.ended:
                return
            await conn.send_audio(chunk)

    async def _pump_live(
        self,
        conn: LiveConnection,
        spec: LiveAgentSpec,
        transport: AudioTransport,
        registry: ToolRegistry,
        moderator: StreamModerator,
        ctx: LiveCallContext,
        emitter: LiveEventEmitter,
        state: _CallState,
    ) -> None:
        buffer_s = max(spec.moderation_buffer_ms, 0) / 1000.0
        async for event in conn.receive():
            if event.function_calls:
                await self._handle_function_calls(
                    event.function_calls, conn, transport, registry, ctx, emitter, state
                )

            if event.interrupted:
                await transport.cut_playback()

            if event.input_transcript_delta:
                state.lead_spoke = True
                state.input_text += event.input_transcript_delta
                if detect_opt_out(state.input_text):
                    await self._handle_opt_out(transport, state)
                    return

            if event.output_transcript_delta:
                if not state.turn_has_output and state.input_text:
                    await transport.send_event(
                        {"type": "transcript", "role": "lead", "text": state.input_text}
                    )
                    state.input_text = ""
                state.turn_has_output = True
                state.output_text += event.output_transcript_delta
                await self._check_moderation(conn, transport, moderator, emitter, state)

            if event.audio and not state.blocked:
                await self._schedule_send(transport, event.audio, buffer_s, state)

            if event.turn_complete:
                if state.output_text:
                    await transport.send_event(
                        {"type": "transcript", "role": "agent", "text": state.output_text}
                    )
                state.output_text = ""
                state.turn_has_output = False
                state.blocked = False

    # -------------------------------------------------------------- opt-out --- #
    async def _handle_opt_out(self, transport: AudioTransport, state: _CallState) -> None:
        """A DNC opt-out phrase was detected in the caller's own transcribed speech.
        Locked guardrail (D-security): honored immediately, in code — cut Live off,
        never let it negotiate or ask a follow-up."""
        state.outcome = LiveOutcome.OPTED_OUT
        state.ended = True
        state.blocked = True
        for t in list(state.pending_sends):
            t.cancel()
        await transport.cut_playback()
        await transport.send_event({"type": "transcript", "role": "lead", "text": state.input_text})
        await self._speak(transport, OPT_OUT_ACK)
        await transport.send_event({"type": "transcript", "role": "agent", "text": OPT_OUT_ACK})

    # ------------------------------------------------------------ moderation --- #
    async def _check_moderation(
        self,
        conn: LiveConnection,
        transport: AudioTransport,
        moderator: StreamModerator,
        emitter: LiveEventEmitter,
        state: _CallState,
    ) -> None:
        verdict = await moderator.check(state.output_text)
        if verdict == ModerationVerdict.BLOCK:
            if state.blocked:
                return  # already cut for this turn
            state.blocked = True
            for t in list(state.pending_sends):
                t.cancel()
            await transport.cut_playback()
            await emitter.emit(
                EventType.GUARDRAIL_TRIPPED,
                {"reason": "moderation_block", "text": state.output_text},
                severity=Severity.WARNING,
            )
            await transport.send_event({"type": "moderation", "verdict": verdict.value})
            await conn.send_steer(STEER_INSTRUCTION)
        elif verdict == ModerationVerdict.FLAG:
            await transport.send_event({"type": "moderation", "verdict": verdict.value})

    # -------------------------------------------------------- buffered audio --- #
    async def _schedule_send(
        self, transport: AudioTransport, chunk: bytes, delay_s: float, state: _CallState
    ) -> None:
        """Hold one audio chunk for the moderation delay budget before forwarding it,
        so a BLOCK detected from the (slightly ahead) transcript can cancel it before
        it's ever heard."""

        async def _later() -> None:
            if delay_s > 0:
                await asyncio.sleep(delay_s)
            if not state.blocked:
                await transport.send_audio(chunk)

        task = asyncio.create_task(_later())
        state.pending_sends.append(task)
        task.add_done_callback(lambda t: state.pending_sends.remove(t) if t in state.pending_sends else None)

    # --------------------------------------------------------- tool calls --- #
    async def _handle_function_calls(
        self,
        calls: list[LiveFunctionCall],
        conn: LiveConnection,
        transport: AudioTransport,
        registry: ToolRegistry,
        ctx: LiveCallContext,
        emitter: LiveEventEmitter,
        state: _CallState,
    ) -> None:
        responses: list[dict[str, Any]] = []
        for call in calls:
            await emitter.emit(EventType.TOOL_INVOKED, {"tool": call.name, "args": call.args})
            # UI-shaped, not audit-shaped (contracts.events.EventType has no tool
            # type of its own) — Live only ever declares IN_CALL tools (P4-1's
            # compiler never exposes a POST_CALL one), so timing is always in_call
            # for anything reaching this handler.
            await transport.send_event({"type": "tool", "name": call.name, "timing": "in_call"})
            tool_ctx = _resolve_tool_context(registry, call.name, ctx)
            try:
                handler = registry.handler_for(call.name)
                result = await handler.execute(call.args, tool_ctx)
            except Exception as exc:  # handler rejected (guardrail) or failed
                await emitter.emit(
                    EventType.GUARDRAIL_TRIPPED,
                    {"tool": call.name, "reason": str(exc)},
                    severity=Severity.WARNING,
                )
                result = {"ok": False, "error": str(exc)}

            if isinstance(result, dict) and result.get("booked") is True:
                state.outcome = LiveOutcome.BOOKED
                await emitter.emit(EventType.SLOT_BOOKED, {"result": result})

            responses.append({"id": call.id, "name": call.name, "response": result})

        if responses:
            await conn.send_tool_response(responses)


def _resolve_tool_context(registry: ToolRegistry, name: str, ctx: LiveCallContext) -> ToolContext:
    """The registry OWNS context/connection resolution (contract: a handler never
    picks its own tenant). Duck-typed like `CallEngine._execute_tool`, so the frozen
    `ToolRegistry` Protocol (which doesn't declare `resolve_context`) is untouched."""
    resolve = getattr(registry, "resolve_context", None)
    if callable(resolve):
        return resolve(name, ctx.tenant_id, campaign_id=ctx.campaign_id, lead_id=ctx.lead_id)
    return ToolContext(tenant_id=ctx.tenant_id, campaign_id=ctx.campaign_id, lead_id=ctx.lead_id)
