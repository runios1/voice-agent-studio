"""BuilderLoop — one user turn in, a stream of token/patch/notice events out.

Flow per turn (D-reliability: constrain -> validate -> gracefully recover):
  1. Build messages: interviewer system prompt (from current config) + history +
     the new user turn.
  2. Ask the model (schema-constrained tool-calling) for its reply + tool calls.
  3. Route each tool call through the gate. Accepted -> emit a `patch` (and a
     synthetic meta.status patch when the agent flips to READY). Rejected ->
     GateError.
  4. If any calls were rejected and retries remain, feed the typed errors back to
     the model as tool results and let it self-correct (bounded). When retries are
     exhausted, unresolved rejections become conversational `notice`s.
  5. Emit the assistant's text as `token`s and persist the turn.

The gate — not this loop — is the security boundary. This loop's triage is UX.
"""

from __future__ import annotations

import json
import re
from typing import AsyncIterator

from contracts.config_schema.schema import AgentStatus
from contracts.model_wrapper.interface import Message, ModelResponse, ModelWrapper, ToolCall

from . import tools
from .completeness import describe_gap, remaining_gaps
from .events import BuilderEvent, NoticeEvent, PatchEvent, TokenEvent
from .gate import Gate, GateAccepted, GateError, get_by_path
from .interviewer import build_system_prompt
from .session import BuilderSession, SessionStore

_TOKEN_RE = re.compile(r"\S+\s*")


def _tokenize(text: str) -> list[str]:
    """Split into chunks whose concatenation reconstructs `text` exactly, so the
    token stream mimics streaming without losing/altering content."""
    return _TOKEN_RE.findall(text) or ([text] if text else [])


class BuilderLoop:
    def __init__(
        self,
        model: ModelWrapper,
        gate: Gate,
        sessions: SessionStore,
        max_retries: int = 2,
    ) -> None:
        self._model = model
        self._gate = gate
        self._sessions = sessions
        self._max_retries = max_retries

    async def run_turn(self, agent_id: str, user_text: str) -> AsyncIterator[BuilderEvent]:
        session = self._sessions.load(agent_id)

        # Empty turn on a fresh session = the builder OPENS the conversation (greets
        # and asks the first question) rather than waiting for the user to start.
        if not user_text.strip():
            if not session.history:
                opening = await self._compose_opening(agent_id, session)
                for chunk in _tokenize(opening):
                    yield TokenEvent(text=chunk)
                session.history.append(Message(role="assistant", content=opening))
                self._sessions.save(session)
            return

        session.history.append(Message(role="user", content=user_text))

        # System prompt reflects the CURRENT config (its remaining gaps steer the ask).
        system = Message(role="system", content=build_system_prompt(self._gate.get_config(agent_id)))
        working: list[Message] = [system, *session.history]

        final_text = ""
        applied: list[GateAccepted] = []
        attempt = 0
        while True:
            response: ModelResponse = await self._model.complete(
                working, tools=tools.BUILDER_TOOLS, model_tier="frontier"
            )
            final_text = response.text or ""

            accepted: list[GateAccepted] = []
            rejected: list[tuple[ToolCall, GateError]] = []
            for call in response.tool_calls:
                try:
                    accepted.append(self._apply(agent_id, call))
                except GateError as err:
                    rejected.append((call, err))

            # Emit patches for everything the gate accepted this attempt.
            for acc in accepted:
                yield PatchEvent(path=acc.patch.path, value=acc.patch.value)
                if acc.status_changed and acc.status == AgentStatus.READY:
                    # Synthetic patch so the panel can react to deploy-readiness.
                    yield PatchEvent(path="meta.status", value=AgentStatus.READY.value)
            applied.extend(accepted)

            if rejected and attempt < self._max_retries:
                # Feed the model its own tool calls + the typed errors, and let it
                # self-correct within the bounded budget.
                attempt += 1
                working = working + [
                    Message(role="assistant", content=_describe_calls(response)),
                    *[
                        Message(role="tool", content=_error_feedback(call, err))
                        for call, err in rejected
                    ],
                ]
                continue

            # Terminal: unresolved rejections become conversational notices.
            for call, err in rejected:
                yield NoticeEvent(kind=err.kind, message=err.message, path=err.path)
            break

        # A Gemini tool-call turn carries NO assistant text (it's function-call parts
        # only), so a turn that recorded answers would otherwise say nothing. If the
        # model didn't already speak, do a second, TOOL-FREE pass so the interviewer
        # actually talks — confirms what it captured and asks the next question. This
        # is the second half of the tool-use pattern and what makes the builder a
        # conversational goal-seeker rather than a silent form-filler (D12).
        if not final_text.strip():
            final_text = await self._compose_reply(agent_id, session, applied, rejected)

        for chunk in _tokenize(final_text):
            yield TokenEvent(text=chunk)

        session.history.append(Message(role="assistant", content=final_text))
        self._sessions.save(session)

    async def _compose_opening(self, agent_id: str, session: BuilderSession) -> str:
        """The builder's first message: greet and ask the first question. Tool-free
        (nothing to record yet); the system prompt already carries the completeness
        gaps so the model asks about the right thing first. Deterministic fallback so
        the chat is never blank on load."""
        system = Message(
            role="system", content=build_system_prompt(self._gate.get_config(agent_id))
        )
        nudge = Message(
            role="user",
            content=(
                "Start the conversation. In one or two short, friendly sentences, "
                "greet me, say you'll help me build my voice SDR agent, and ask the "
                "first question toward that. Do not call any tools yet."
            ),
        )
        try:
            resp = await self._model.complete([system, nudge], model_tier="frontier")
            text = (resp.text or "").strip()
            if text:
                return text
        except Exception:
            pass
        return (
            "Hi! I'll help you build your voice SDR agent. To start — what's its role, "
            "and which company will it be calling on behalf of?"
        )

    async def _compose_reply(
        self,
        agent_id: str,
        session: BuilderSession,
        applied: list[GateAccepted],
        rejected: list[tuple[ToolCall, GateError]],
    ) -> str:
        """Generate the spoken reply for a turn whose model response was tool-calls
        only. The builder is a GOAL-SEEKING interviewer (D12): it confirms what it
        saved and then asks about the SPECIFIC next required field still missing —
        it does not just make open-ended conversation. The next gap is computed in
        CODE from the (now-updated) config, so both the model nudge and the
        deterministic fallback stay on-goal even if the model turn comes back empty."""
        config = self._gate.get_config(agent_id)
        gaps = remaining_gaps(config)
        next_gap = gaps[0] if gaps else None

        notes: list[str] = []
        if applied:
            recorded = "; ".join(f"{a.patch.path} = {a.patch.value!r}" for a in applied)
            notes.append(f"Saved: {recorded}.")
        for call, err in rejected:
            notes.append(f"Could not apply {call.name}: {err.message}")
        result = " ".join(notes) if notes else "No changes were made this turn."

        if next_gap is not None:
            directive = (
                f"{result} Reply to the user in ONE or two short sentences: briefly "
                f"confirm what you captured, then ask specifically about the NEXT "
                f"missing detail — {describe_gap(next_gap)}. Ask about that one thing "
                f"only, as a natural question. Do not call any tools; just talk."
            )
        else:
            directive = (
                f"{result} Every required field is now filled — the agent is "
                f"deploy-ready. In one or two short sentences, tell the user it's "
                f"ready to test in Preview and offer to add optional detail (objection "
                f"handling, style notes). Do not call any tools."
            )

        system = Message(role="system", content=build_system_prompt(config))
        # A plain user-role instruction: the model reliably answers it with text,
        # where a "[tool result]"-prefixed turn sometimes came back empty.
        nudge = Message(role="user", content=directive)
        try:
            resp = await self._model.complete(
                [system, *session.history, nudge], model_tier="frontier"
            )
            text = (resp.text or "").strip()
            if text:
                return text
        except Exception:
            pass  # never surface a stack trace; use the deterministic fallback below

        # Deterministic fallback — still goal-directed: name the next gap explicitly.
        if rejected:
            return rejected[0][1].message
        lead = "Got it — saved." if applied else "Okay."
        if next_gap is not None:
            return f"{lead} Next, let's cover {describe_gap(next_gap)}."
        return (
            f"{lead} That's everything required — your agent is ready to test in "
            "Preview. Want to add objection handling or style notes?"
        )

    # ----------------------------------------------------------------------- #
    # Tool-call routing. Every write goes through the gate (never direct).
    # List-append helpers read-modify-write the whole list so the gate's
    # set-semantics patch contract ({path, value}) is preserved.
    # ----------------------------------------------------------------------- #
    def _apply(self, agent_id: str, call: ToolCall) -> GateAccepted:
        name = call.name
        args = call.arguments

        if name == tools.SET_FIELD:
            return self._gate.apply_patch(agent_id, args["path"], args["value"])

        if name == tools.ADD_QUALIFICATION_CRITERION:
            config = self._gate.get_config(agent_id)
            current = [c.model_dump() for c in config.conversation.qualification.criteria]
            current.append(
                {
                    "label": args["label"],
                    "question": args.get("question"),
                    "disqualifying": args.get("disqualifying", False),
                }
            )
            return self._gate.apply_patch(agent_id, "conversation.qualification.criteria", current)

        if name == tools.ADD_OBJECTION:
            config = self._gate.get_config(agent_id)
            current = [o.model_dump() for o in config.conversation.objections]
            current.append(
                {"trigger": args["trigger"], "response_guidance": args["response_guidance"]}
            )
            return self._gate.apply_patch(agent_id, "conversation.objections", current)

        if name == tools.PUSH_TO_WISHLIST:
            config = self._gate.get_config(agent_id)
            current = list(config.wishlist)
            current.append(args["item"])
            return self._gate.apply_patch(agent_id, "wishlist", current)

        if name == tools.CLEAR_FIELD:
            config = self._gate.get_config(agent_id)
            current = get_by_path(config.model_dump(), args["path"])
            empty: object = [] if isinstance(current, list) else None
            return self._gate.apply_patch(agent_id, args["path"], empty)

        # Unknown tool name — treat as a validation slip the model can recover from.
        raise GateError(kind="validation", message=f"Unknown tool '{name}'.", path=None)


def _describe_calls(response: ModelResponse) -> str:
    return json.dumps(
        [{"name": c.name, "arguments": c.arguments} for c in response.tool_calls]
    )


def _error_feedback(call: ToolCall, err: GateError) -> str:
    return json.dumps(
        {
            "tool": call.name,
            "arguments": call.arguments,
            "rejected": True,
            "error_kind": err.kind,
            "path": err.path,
            "reason": err.message,
            "hint": "Correct the value or path and retry, or explain to the user if it cannot be done.",
        }
    )
