"""Deterministic mocks for the contracts P2-1 consumes but that aren't merged yet:
the model wrapper (P2-6/WS6), and the tool registry + handlers (P2-3). All are
scripted so tests assert exactly what the runtime did.

  * `ScriptedToolWrapper` — a `ModelWrapper` whose `complete()` returns a scripted
    sequence of ModelResponses (text and/or tool_calls), so the in-call tool path is
    exercised without a real model. Records every call.
  * `MockToolRegistry` / `MockToolHandler` — a `ToolRegistry` over a fixed catalog
    (calendar `book_meeting`, email `send_email`, IN_CALL). Handlers enforce a sample
    guardrail (business-hours on booking) by RAISING — the same rejection shape a real
    P2-3 handler uses — so the engine's GUARDRAIL_TRIPPED path is real in CI.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, AsyncIterator, Optional, Union

from contracts.model_wrapper.interface import (
    Message,
    ModelResponse,
    ModelWrapper,
    ToolCall,
    ToolDef,
)
from contracts.tool_registry.interface import (
    RegistryTool,
    Timing,
    ToolContext,
    ToolHandler,
)

# ------------------------------------------------------------------ wrapper --- #
Scripted = Union[str, ModelResponse]


class ScriptedToolWrapper(ModelWrapper):
    """Returns a scripted sequence of responses. A `str` entry becomes a text-only
    response; a `ModelResponse` entry is returned verbatim (use for tool calls). The
    last entry repeats if the loop asks for more. Every `complete`/`stream` call is
    recorded on `self.calls` (messages, tools, tier)."""

    def __init__(self, script: Union[Scripted, list[Scripted]] = "Okay.") -> None:
        self._script = script if isinstance(script, list) else [script]
        self._i = 0
        self.calls: list[dict] = []

    def _next(self) -> ModelResponse:
        item = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        if isinstance(item, ModelResponse):
            return item
        return ModelResponse(text=item, tool_calls=[])

    async def complete(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDef]] = None,
        response_schema: Optional[dict] = None,
        model_tier: str = "frontier",
    ) -> ModelResponse:
        self.calls.append({"messages": messages, "tools": tools, "model_tier": model_tier})
        return self._next()

    async def stream(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDef]] = None,
        model_tier: str = "frontier",
    ) -> AsyncIterator[str]:
        self.calls.append({"messages": messages, "tools": tools, "model_tier": model_tier})
        text = self._next().text or ""
        for word in text.split(" "):
            yield word + " "

    @property
    def last_system_prompt(self) -> str:
        for msg in self.calls[-1]["messages"]:
            if msg.role == "system":
                return msg.content
        return ""


def tool_call(name: str, **arguments: Any) -> ModelResponse:
    """Sugar: a ModelResponse that is a single tool call (no text)."""
    return ModelResponse(text=None, tool_calls=[ToolCall(name=name, arguments=arguments)])


# ----------------------------------------------------------------- registry --- #
# name MATCHES the automation block ("calendar"), per the frozen registry contract —
# that name is also the model-facing function name via to_tool_def().
_BOOK_MEETING = RegistryTool(
    name="calendar",
    description="Book a meeting slot on the connected calendar. Business hours and "
    "booking window are enforced by the handler, not by you.",
    timing=Timing.IN_CALL,
    params={
        "type": "object",
        "properties": {
            "start_iso": {"type": "string", "description": "Proposed start time, ISO-8601."}
        },
        "required": ["start_iso"],
        "additionalProperties": False,
    },
    provider="google_calendar",
    required_scopes=["https://www.googleapis.com/auth/calendar.events"],
)

_SEND_EMAIL = RegistryTool(
    name="email",
    description="Send one of the pre-approved email templates.",
    timing=Timing.POST_CALL,  # not exposed in-call
    params={
        "type": "object",
        "properties": {"template_id": {"type": "string"}},
        "required": ["template_id"],
        "additionalProperties": False,
    },
    provider="gmail",
)


class MockBookMeetingHandler:
    """Books a slot, enforcing a sample guardrail IN CODE (the enforcement point,
    D6/D-security): reject slots outside 09:00–17:00. Rejection == raising, which the
    engine turns into a GUARDRAIL_TRIPPED event."""

    def __init__(self, business_start: int = 9, business_end: int = 17) -> None:
        self.business_start = business_start
        self.business_end = business_end
        self.booked: list[dict[str, Any]] = []

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        start = datetime.fromisoformat(args["start_iso"])
        if not (self.business_start <= start.hour < self.business_end):
            raise ValueError(
                f"slot {start.isoformat()} is outside business hours "
                f"{self.business_start:02d}:00–{self.business_end:02d}:00"
            )
        record = {"start_iso": args["start_iso"], "tenant_id": ctx.tenant_id, "lead_id": ctx.lead_id}
        self.booked.append(record)
        return {"booked": True, **record}


class MockToolRegistry:
    """A `ToolRegistry` over a fixed catalog. `book_meeting` is IN_CALL and guardrailed;
    `email` is POST_CALL (so it never appears in the in-call tool list)."""

    def __init__(self, book_handler: Optional[MockBookMeetingHandler] = None) -> None:
        self._tools = {t.name: t for t in (_BOOK_MEETING, _SEND_EMAIL)}
        self._book_handler: ToolHandler = book_handler or MockBookMeetingHandler()

    def list_tools(self, timing: Optional[Timing] = None) -> list[RegistryTool]:
        return [t for t in self._tools.values() if timing is None or t.timing == timing]

    def get(self, name: str) -> Optional[RegistryTool]:
        return self._tools.get(name)

    def handler_for(self, name: str) -> ToolHandler:
        if name == "calendar":
            return self._book_handler
        raise KeyError(f"no handler for {name!r}")
