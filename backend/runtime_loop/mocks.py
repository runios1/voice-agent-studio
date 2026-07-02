"""Scripted mock ModelWrapper for Phase-1 tests and the demo surface.

WS4 depends on the model wrapper (WS6) via the frozen `ModelWrapper` interface, but
must run before WS6 is merged — so we mock it here (per the dispatch protocol). This
mock is deterministic: it yields scripted tokens and records every call (messages,
tools, tier) so tests can assert exactly what the runtime handed the model — e.g.
that locked guardrails preceded persona, that `wishlist` was absent, and that only
declared tools were passed.
"""

from __future__ import annotations

from typing import AsyncIterator, Callable, Optional, Union

from contracts.model_wrapper.interface import (
    Message,
    ModelResponse,
    ModelWrapper,
    ToolDef,
)

ReplyFn = Callable[[list[Message]], str]


class ScriptedWrapper(ModelWrapper):
    """A ModelWrapper that returns canned text.

    `reply` may be a single string (used every turn), a list of strings (one per
    turn, last repeats), or a callable of the messages. All calls are recorded on
    `self.calls`. Tokenization for `stream` is by whitespace to mimic streaming.
    """

    def __init__(self, reply: Union[str, list[str], ReplyFn] = "Sure, happy to help.") -> None:
        self._reply = reply
        self._turn = 0
        self.calls: list[dict] = []

    def _next_reply(self, messages: list[Message]) -> str:
        if callable(self._reply):
            text = self._reply(messages)
        elif isinstance(self._reply, list):
            idx = min(self._turn, len(self._reply) - 1)
            text = self._reply[idx]
        else:
            text = self._reply
        self._turn += 1
        return text

    async def complete(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDef]] = None,
        response_schema: Optional[dict] = None,
        model_tier: str = "frontier",
    ) -> ModelResponse:
        self.calls.append({"messages": messages, "tools": tools, "model_tier": model_tier})
        return ModelResponse(text=self._next_reply(messages), tool_calls=[])

    async def stream(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDef]] = None,
        model_tier: str = "frontier",
    ) -> AsyncIterator[str]:
        self.calls.append({"messages": messages, "tools": tools, "model_tier": model_tier})
        text = self._next_reply(messages)
        words = text.split(" ")
        for i, word in enumerate(words):
            yield word if i == len(words) - 1 else word + " "

    @property
    def last_system_prompt(self) -> str:
        """Convenience: the system prompt from the most recent call."""
        for msg in self.calls[-1]["messages"]:
            if msg.role == "system":
                return msg.content
        return ""
