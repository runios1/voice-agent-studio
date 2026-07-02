"""
FROZEN CONTRACT — Provider-agnostic model wrapper interface
===========================================================

Every model call in the product goes through this interface (D8/D9). Reasons:

  * builder model and voice model may be DIFFERENT providers (D9) — voice
    frameworks are model-agnostic, so we don't lock to one vendor;
  * "which model" becomes a config line, not an architecture decision;
  * the security screening layer (D-security) wraps EVERY call in one place;
  * AI-Studio -> Vertex migration is a swap behind this interface, not a rewrite.

The concrete Gemini adapter lives in backend/wrapper_impl. Do NOT import provider
SDKs anywhere except behind an implementation of this interface.

This is a STUB: signatures + docstrings are the contract. No implementation here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional


@dataclass
class Message:
    role: str            # "system" | "user" | "assistant" | "tool"
    content: str


@dataclass
class ToolDef:
    """A function the model may call. `parameters` is a JSON Schema object.

    Schema-constrained tool-calling is how malformed output is made STRUCTURALLY
    IMPOSSIBLE at the source (D-reliability). Handlers for these are owned by the
    caller (builder loop / runtime loop) — the model only emits the call.
    """
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class ModelResponse:
    text: Optional[str]
    tool_calls: list[ToolCall]


class ModelWrapper(ABC):
    """Provider-agnostic entry point. Implementations: GeminiWrapper (v1),
    OpenAIWrapper / ClaudeWrapper (later, if ever). Screening is applied by a
    decorator around any implementation (see backend/security)."""

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDef]] = None,
        response_schema: Optional[dict[str, Any]] = None,
        model_tier: str = "frontier",   # "frontier" (builder) | "fast" | "voice"
    ) -> ModelResponse:
        """Single-shot completion, optionally schema-constrained / tool-enabled."""
        raise NotImplementedError

    @abstractmethod
    def stream(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDef]] = None,
        model_tier: str = "frontier",
    ) -> AsyncIterator[str]:
        """Token stream for the chat surfaces (builder + preview), fed to SSE."""
        raise NotImplementedError
