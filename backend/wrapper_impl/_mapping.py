"""Pure translation between the frozen contract types and Gemini SDK types.

Kept free of network / client concerns so it is exhaustively unit-testable. The
GeminiWrapper is a thin async shell around these functions.

Role mapping (contract Message.role -> Gemini):
  * ``system``    -> hoisted out of the turn list into ``system_instruction``.
  * ``user``      -> Content(role="user").
  * ``assistant`` -> Content(role="model").      # Gemini calls it "model"
  * ``tool``      -> Content(role="user"), text prefixed "[tool result] ".
        LOSSY (Phase 1): the frozen Message carries no function name, so a faithful
        Gemini function_response part can't be reconstructed. This is fine for the
        preview/builder flows, which only need the *text* of a tool result echoed
        back. If true typed function-response round-trips are ever needed, that's a
        contract gap (Message needs an optional name) -> file a change request; do
        NOT bend the contract silently. See DONE.md.

tools/response_schema are mutually exclusive: Gemini can't do function-calling and
structured-JSON output in one generation, so supplying both is a caller bug and we
fail fast (see build_config).
"""

from __future__ import annotations

from typing import Any, Optional

from google.genai import types

from contracts.model_wrapper.interface import (
    Message,
    ModelResponse,
    ToolCall,
    ToolDef,
)

_TOOL_RESULT_PREFIX = "[tool result] "


class WrapperUsageError(ValueError):
    """Caller supplied an unsupported combination of arguments."""


def split_messages(
    messages: list[Message],
) -> tuple[Optional[str], list[types.Content]]:
    """Return (system_instruction, contents). System turns are concatenated and
    hoisted; every other turn becomes a Content in order."""
    system_parts: list[str] = []
    contents: list[types.Content] = []

    for m in messages:
        if m.role == "system":
            if m.content:
                system_parts.append(m.content)
            continue
        if m.role == "assistant":
            role, text = "model", m.content
        elif m.role == "tool":
            role, text = "user", _TOOL_RESULT_PREFIX + m.content
        else:  # "user" and any unknown role default to a user turn
            role, text = "user", m.content
        contents.append(types.Content(role=role, parts=[types.Part(text=text)]))

    system_instruction = "\n\n".join(system_parts) if system_parts else None
    return system_instruction, contents


def to_tools(tools: Optional[list[ToolDef]]) -> Optional[list[types.Tool]]:
    """Map contract ToolDefs to a single Gemini Tool with function declarations.
    ``parameters`` is passed through as a raw JSON Schema (parameters_json_schema)
    so the schema-constrained shape is preserved exactly (D-reliability)."""
    if not tools:
        return None
    declarations = [
        types.FunctionDeclaration(
            name=t.name,
            description=t.description,
            parameters_json_schema=t.parameters,
        )
        for t in tools
    ]
    return [types.Tool(function_declarations=declarations)]


def build_config(
    *,
    system_instruction: Optional[str],
    tools: Optional[list[ToolDef]],
    response_schema: Optional[dict[str, Any]],
    timeout_s: float,
) -> types.GenerateContentConfig:
    """Assemble a GenerateContentConfig, enforcing the tools/response_schema
    mutual-exclusion at the boundary."""
    if tools and response_schema is not None:
        raise WrapperUsageError(
            "tools and response_schema are mutually exclusive in this wrapper: "
            "Gemini cannot do function-calling and structured-JSON output in one "
            "generation. Pass one or the other."
        )

    cfg = types.GenerateContentConfig(
        system_instruction=system_instruction,
        http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),  # ms
    )

    if tools:
        cfg.tools = to_tools(tools)
        # We hand the caller the parsed ToolCall and let them run it — never let the
        # SDK auto-invoke a Python function on our behalf.
        cfg.automatic_function_calling = types.AutomaticFunctionCallingConfig(
            disable=True
        )
    elif response_schema is not None:
        cfg.response_mime_type = "application/json"
        cfg.response_json_schema = response_schema

    return cfg


def to_model_response(response: types.GenerateContentResponse) -> ModelResponse:
    """Collapse a Gemini response into the contract's ModelResponse shape."""
    tool_calls: list[ToolCall] = []
    for fc in response.function_calls or []:
        tool_calls.append(ToolCall(name=fc.name, arguments=dict(fc.args or {})))

    # response.text raises/ warns if the sole part is a function_call; guard it.
    text: Optional[str] = None
    try:
        text = response.text
    except (ValueError, AttributeError):
        text = None

    return ModelResponse(text=text, tool_calls=tool_calls)


def text_delta(chunk: types.GenerateContentResponse) -> Optional[str]:
    """Extract only the text delta from a streamed chunk; function-call parts are
    dropped (the streaming surface is text-only per the contract's str yield)."""
    try:
        return chunk.text or None
    except (ValueError, AttributeError):
        return None
