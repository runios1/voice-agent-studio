"""
ScreeningModelWrapper — the decorator that puts screening around EVERY model call.

Wraps any `ModelWrapper` implementation (D-security: "wrap EVERY model in/out via
the ModelWrapper boundary"). It IS-A ModelWrapper, so callers (builder / runtime
loop) construct it once around the real Gemini wrapper and are otherwise unchanged:

    wrapper = ScreeningModelWrapper(GeminiWrapper(...), screener=my_screener)

Inbound: every message's content is screened before it reaches the model.
Outbound: `complete()` output text + tool-call argument strings are screened
before they are returned to the caller.

On a hard block, we raise `ScreeningBlocked` (typed, conversational message) rather
than returning garbage — the caller converts it to the API's `notice` (D-reliability).

Streaming caveat (documented, not hidden): `stream()` screens the inbound messages,
then delegates token streaming. Per-token OUTBOUND screening is intentionally NOT
done inline — buffering the whole stream would defeat streaming, and any streamed
content that becomes config is re-screened at the config gate (defense in depth).
Use `complete()` when you need outbound screening on a single-shot call. A helper,
`stream_screened_buffered()`, is provided for callers that want full-text outbound
screening at the cost of latency.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional

from contracts.model_wrapper.interface import (
    Message,
    ModelResponse,
    ModelWrapper,
    ToolCall,
    ToolDef,
)

from .config import ScreeningConfig
from .engine import screen_text
from .errors import ScreeningBlocked
from .models import Direction, ScreenDecision
from .screener import Screener


class ScreeningModelWrapper(ModelWrapper):
    def __init__(
        self,
        inner: ModelWrapper,
        screener: Screener,
        *,
        config: ScreeningConfig | None = None,
    ) -> None:
        self._inner = inner
        self._screener = screener
        self._config = config or ScreeningConfig.from_env()

    # -- inbound / outbound helpers ---------------------------------------- #

    async def _screen_or_raise(
        self, text: str, direction: Direction, *, context: str
    ) -> ScreenDecision:
        decision = await screen_text(
            self._screener, text, direction, self._config, context=context
        )
        if decision.blocked:
            raise ScreeningBlocked(
                decision.message, direction=direction, findings=decision.findings
            )
        return decision

    async def _screen_inbound(self, messages: list[Message]) -> None:
        for i, msg in enumerate(messages):
            await self._screen_or_raise(
                msg.content, Direction.INBOUND, context=f"in:{msg.role}#{i}"
            )

    async def _screen_outbound(self, resp: ModelResponse) -> None:
        if resp.text:
            await self._screen_or_raise(resp.text, Direction.OUTBOUND, context="out:text")
        for call in resp.tool_calls:
            payload = _stringify_args(call.arguments)
            if payload:
                await self._screen_or_raise(
                    payload, Direction.OUTBOUND, context=f"out:tool:{call.name}"
                )

    # -- ModelWrapper interface -------------------------------------------- #

    async def complete(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDef]] = None,
        response_schema: Optional[dict[str, Any]] = None,
        model_tier: str = "frontier",
    ) -> ModelResponse:
        await self._screen_inbound(messages)
        resp = await self._inner.complete(
            messages, tools=tools, response_schema=response_schema, model_tier=model_tier
        )
        await self._screen_outbound(resp)
        return resp

    async def stream(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDef]] = None,
        model_tier: str = "frontier",
    ) -> AsyncIterator[str]:
        # Screen inbound BEFORE any token leaves the model; a block prevents the call.
        await self._screen_inbound(messages)
        async for token in self._inner.stream(messages, tools=tools, model_tier=model_tier):
            yield token

    async def stream_screened_buffered(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDef]] = None,
        model_tier: str = "frontier",
    ) -> AsyncIterator[str]:
        """Like stream(), but buffers the full response and screens it OUTBOUND
        before yielding anything. Trades streaming latency for outbound screening;
        use where an unscreened partial emission is unacceptable."""
        await self._screen_inbound(messages)
        chunks: list[str] = []
        async for token in self._inner.stream(messages, tools=tools, model_tier=model_tier):
            chunks.append(token)
        full = "".join(chunks)
        await self._screen_or_raise(full, Direction.OUTBOUND, context="out:stream")
        if full:
            yield full


def _stringify_args(arguments: dict[str, Any]) -> str:
    """Flatten tool-call arguments to a single screenable string."""
    if not arguments:
        return ""
    try:
        return json.dumps(arguments, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return " ".join(str(v) for v in arguments.values())
