"""GeminiWrapper — the v1 concrete ModelWrapper (D8/D9).

THE ONLY place a provider SDK is imported (this module + _mapping/_config). Every
model call in the product flows through the ModelWrapper interface; screening is
applied by a decorator in backend/security, NOT here (WS6 boundary).

Reliability (D-reliability): a per-call timeout plus bounded exponential-backoff
retry on *transient* failures only (timeouts, 429, 5xx). Non-transient errors
(bad request, auth) fail immediately — retrying them just wastes latency.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, AsyncIterator, Optional

import google.genai as genai
from google.genai import errors as genai_errors
from google.genai import types

from contracts.model_wrapper.interface import (
    Message,
    ModelResponse,
    ModelWrapper,
    ToolDef,
)

from . import _mapping
from .config import GeminiConfig

# Re-export so callers/tests can catch the boundary error without importing _mapping.
WrapperUsageError = _mapping.WrapperUsageError


class GeminiWrapper(ModelWrapper):
    """Google Gemini implementation of the provider-agnostic ModelWrapper."""

    def __init__(
        self,
        config: Optional[GeminiConfig] = None,
        *,
        client: Optional[Any] = None,
    ) -> None:
        """`config` defaults to GeminiConfig.from_env(). `client` is an injection
        seam for tests — production passes nothing and a real async client is built.
        """
        self._config = config or GeminiConfig.from_env()
        self._client = client or self._build_client(self._config)

    @staticmethod
    def _build_client(config: GeminiConfig) -> genai.Client:
        """Construct the SDK client. AI-Studio (api_key) today; the same client
        switches to Vertex via a flag (D8) — a config change, not a rewrite."""
        if config.use_vertex:
            return genai.Client(
                vertexai=True,
                project=config.vertex_project,
                location=config.vertex_location,
            )
        return genai.Client(api_key=config.api_key)

    async def complete(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDef]] = None,
        response_schema: Optional[dict[str, Any]] = None,
        model_tier: str = "frontier",
    ) -> ModelResponse:
        system_instruction, contents = _mapping.split_messages(messages)
        config = _mapping.build_config(
            system_instruction=system_instruction,
            tools=tools,
            response_schema=response_schema,
            timeout_s=self._config.timeout_s,
        )
        model = self._config.model_for(model_tier)

        async def _call() -> types.GenerateContentResponse:
            return await self._client.aio.models.generate_content(
                model=model, contents=contents, config=config
            )

        response = await self._with_retry(_call)
        return _mapping.to_model_response(response)

    async def stream(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDef]] = None,
        model_tier: str = "frontier",
    ) -> AsyncIterator[str]:
        """Yield text deltas only (contract yields str). Function-call parts are
        dropped from the stream; structured tool-calls go through complete()."""
        system_instruction, contents = _mapping.split_messages(messages)
        config = _mapping.build_config(
            system_instruction=system_instruction,
            tools=tools,
            response_schema=None,
            timeout_s=self._config.timeout_s,
        )
        model = self._config.model_for(model_tier)

        # Retry only the connection/first-response; once tokens flow we don't restart
        # a partially-delivered stream (that would duplicate emitted text).
        async def _open() -> AsyncIterator[types.GenerateContentResponse]:
            return await self._client.aio.models.generate_content_stream(
                model=model, contents=contents, config=config
            )

        chunks = await self._with_retry(_open)
        async for chunk in chunks:
            delta = _mapping.text_delta(chunk)
            if delta:
                yield delta

    # ------------------------------------------------------------------ retry ---

    async def _with_retry(self, call):
        """Invoke `call` with bounded exponential backoff on transient errors."""
        attempt = 0
        while True:
            try:
                return await call()
            except _mapping.WrapperUsageError:
                raise  # caller bug — never retry
            except Exception as exc:  # noqa: BLE001 - classified below
                if not _is_transient(exc) or attempt >= self._config.max_retries:
                    raise
                delay = _backoff_delay(attempt)
                attempt += 1
                await asyncio.sleep(delay)


_TRANSIENT_STATUS = {408, 429, 500, 502, 503, 504}


def _is_transient(exc: Exception) -> bool:
    """Timeouts, rate-limits (429) and 5xx are worth retrying; 4xx/auth are not."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True
    if isinstance(exc, genai_errors.ServerError):
        return True
    code = getattr(exc, "code", None)
    if isinstance(code, int) and code in _TRANSIENT_STATUS:
        return True
    # httpx transport/timeout errors surface by class name (avoid a hard httpx dep).
    name = type(exc).__name__
    if "Timeout" in name or "ConnectError" in name or "TransportError" in name:
        return True
    return False


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff with full jitter: ~0.5s, 1s, 2s ... capped at 8s."""
    base = min(0.5 * (2 ** attempt), 8.0)
    return random.uniform(0, base)
