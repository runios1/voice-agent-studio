"""Mocks for the contracts P2-4 consumes but that aren't merged yet: the tool
registry (P2-3), a per-tenant connection resolver (P2-3), and the event sink (P2-5).

These implement the FROZEN interfaces exactly, so swapping in the real components at
integration is a wiring change, not a rewrite. The mock POST_CALL handlers record
every call (so tests can assert exactly-once) and enforce a guardrail in code — an
email may only send an APPROVED template id — to prove the enforcement point lives in
the handler (D6/D-security), not in a prompt or in this stream.
"""

from __future__ import annotations

from typing import Any, Optional

from contracts.events.schema import Event
from contracts.tool_registry.interface import (
    Connection,
    RegistryTool,
    Timing,
    ToolContext,
    ToolRegistry,
)

# The templates the platform has approved. A workflow that references anything else
# is rejected HERE — the model/persona/workflow can't smuggle a body or a link.
APPROVED_EMAIL_TEMPLATES = {
    "booking_confirmation",
    "nurture_nudge",
    "sorry_we_missed_you",
}


class RecordingHandler:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []


class MockEmailHandler(RecordingHandler):
    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        template_id = args.get("template_id")
        if template_id not in APPROVED_EMAIL_TEMPLATES:
            # Guardrail enforced in code — never send an unapproved template.
            raise ValueError(f"template_id not approved: {template_id!r}")
        record = {"template_id": template_id, "tenant_id": ctx.tenant_id, "lead_id": ctx.lead_id}
        self.calls.append(record)
        return {"status": "sent", **record}


class MockCrmHandler(RecordingHandler):
    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        record = {"status": args.get("status"), "tenant_id": ctx.tenant_id, "lead_id": ctx.lead_id}
        self.calls.append(record)
        return {"crm_write": "ok", **record}


class MockToolRegistry(ToolRegistry):
    """A tiny stand-in registry with the two POST_CALL tools P2-4 exercises."""

    def __init__(self) -> None:
        self.email = MockEmailHandler()
        self.crm = MockCrmHandler()
        self._tools = {
            "email": RegistryTool(
                name="email",
                description="Send one approved email template.",
                timing=Timing.POST_CALL,
                params={
                    "type": "object",
                    "properties": {"template_id": {"type": "string"}},
                    "required": ["template_id"],
                    "additionalProperties": False,
                },
                provider="gmail",
                required_scopes=["gmail.send"],
            ),
            "crm": RegistryTool(
                name="crm",
                description="Write a lead status to the CRM.",
                timing=Timing.POST_CALL,
                params={
                    "type": "object",
                    "properties": {"status": {"type": "string"}},
                    "required": ["status"],
                    "additionalProperties": False,
                },
                provider="salesforce",
                required_scopes=["crm.write"],
            ),
        }
        self._handlers = {"email": self.email, "crm": self.crm}

    def list_tools(self, timing: Optional[Timing] = None) -> list[RegistryTool]:
        tools = list(self._tools.values())
        if timing is not None:
            tools = [t for t in tools if t.timing is timing]
        return tools

    def get(self, name: str) -> Optional[RegistryTool]:
        return self._tools.get(name)

    def handler_for(self, name: str):
        return self._handlers[name]


class MockConnectionResolver:
    """Returns a per-tenant connection for any known provider. The real resolver
    (P2-3) enforces tenant isolation; this one just fabricates a scoped handle."""

    async def resolve(self, tenant_id: str, provider: str) -> Optional[Connection]:
        return Connection(
            tenant_id=tenant_id,
            provider=provider,
            connection_ref=f"{tenant_id}:{provider}:conn",
            scopes=[],
        )


class InMemoryEventSink:
    """Stands in for P2-5's write bus. Records emitted events for assertions."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    async def emit(self, event: Event) -> None:
        self.events.append(event)
