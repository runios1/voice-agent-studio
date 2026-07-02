"""The runtime turn loop — the piece you keep (D12).

Phase 1: a text-preview engine. `run_turn` takes a user turn and streams back the
agent's reply, with two invariants enforced in CODE (never left to the prompt):

  1. AI DISCLOSURE (hard step): on the agent's first utterance of a session, if the
     config requires disclosure, a code-emitted disclosure line is streamed FIRST,
     as a prefix of that utterance. It comes from `guardrails.disclosure_line`, not
     the model, so no injected persona can suppress or reword it.
  2. CAPABILITY = EXPOSED FUNCTION: the only tools passed to the model are those
     `tools.build_tools` derives from ENABLED automation. Phase 1 wires no real
     tools; the seam is exact so Phase 2 slots handlers in without a rewrite.

The system prompt is recompiled deterministically each turn from the current config
(so a mid-session config edit takes effect) and orders locked guardrails above user
persona (see compiler.py). `wishlist` never reaches the model.

In Phase 2 the text I/O here is swapped for the voice Live API; the disclosure step,
tool layer, and prompt composition are unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Literal

from contracts.config_schema.schema import AgentConfig
from contracts.model_wrapper.interface import Message, ModelWrapper

from backend.runtime_loop.compiler import compile_system_prompt
from backend.runtime_loop.guardrails import disclosure_line, must_disclose
from backend.runtime_loop.session import PreviewSession, SessionStore
from backend.runtime_loop.tools import build_tools


@dataclass
class TurnEvent:
    kind: Literal["token", "done"]
    text: str = ""


class RuntimeEngine:
    """Executes a config as a conversational agent over a text preview.

    Stateless except for the injected `SessionStore`; safe to share one instance
    across requests. `model_tier` selects which model the wrapper uses — Phase 1
    preview uses the frontier model as a stand-in for the Phase-2 voice tier.
    """

    def __init__(
        self,
        wrapper: ModelWrapper,
        store: SessionStore | None = None,
        *,
        model_tier: str = "frontier",
        expose_declared_tools: bool = False,
    ) -> None:
        self.wrapper = wrapper
        self.store = store or SessionStore()
        self.model_tier = model_tier
        # Phase 1 preview: no real tools executed. Flip on to hand the model the
        # declared tool *definitions* (Phase-2 seam / structural-claim tests).
        self.expose_declared_tools = expose_declared_tools

    async def run_turn(
        self,
        config: AgentConfig,
        session: PreviewSession,
        user_text: str,
    ) -> AsyncIterator[TurnEvent]:
        """Stream the agent's reply to one user turn — OR open the call.

        An outbound SDR speaks first, so an empty `user_text` on a fresh session is
        the AGENT'S OPENING: the code-emitted disclosure fires, then the model
        delivers its opening line, and no user turn is recorded. Otherwise this is a
        normal reply to the user's turn.

        Yields `token` events (disclosure prefix first, if due, then model tokens)
        and a final `done`. The full agent utterance is recorded to session history
        as a single assistant turn.
        """
        opening_turn = not user_text.strip() and not session.messages
        if not opening_turn:
            session.add("user", user_text)

        system_prompt = compile_system_prompt(config, opening_turn=opening_turn)
        tools = build_tools(config, include_declared=self.expose_declared_tools)

        utterance_parts: list[str] = []

        # --- Hard guardrail step: AI disclosure, once per session, code-emitted. ---
        if not session.disclosed and must_disclose(config):
            line = disclosure_line(config)
            session.disclosed = True
            utterance_parts.append(line)
            yield TurnEvent("token", line)
            yield TurnEvent("token", " ")

        # --- Model turn ---
        messages: list[Message] = [Message(role="system", content=system_prompt)]
        if opening_turn:
            # No user turn to react to; nudge the model to deliver its opening. The
            # nudge is not persisted, so history stays a clean agent/user transcript.
            messages.append(
                Message(role="user", content="Begin the call now with your opening.")
            )
        else:
            messages.extend(session.messages)

        async for chunk in self.wrapper.stream(
            messages, tools=tools, model_tier=self.model_tier
        ):
            if not chunk:
                continue
            utterance_parts.append(chunk)
            yield TurnEvent("token", chunk)

        session.add("assistant", "".join(utterance_parts))
        yield TurnEvent("done")
