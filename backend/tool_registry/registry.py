"""The ToolRegistry implementation + the per-agent build.

`InMemoryToolRegistry` satisfies the frozen `ToolRegistry` Protocol (`list_tools`,
`get`, `handler_for`) and adds the two things a caller (voice runtime P2-1, async
workflows P2-4) needs to run a tool safely:

  * `resolve_context(...)` — the registry resolves the `ToolContext`, including the
    tenant's `Connection` for the tool's provider (looked up in the tenant-scoped
    `ConnectionStore`). A handler NEVER picks its own tenant or connection — that is
    the contract's stated division of labor and a load-bearing isolation property.
  * `execute(...)` — convenience that resolves context then runs the handler.

`build_registry(config, ...)` is the entry point: it distills the agent's
`GuardrailPolicy` from the frozen config, injects the concrete approved-template
enum into the email tool's param schema (so the model sees exactly the allowed ids —
empty allowlist ⇒ no valid call, structurally), and wires handlers with the policy,
the encrypted credential store, the event sink, and the (mock) provider clients.

Which tools an agent actually exposes still follows the Phase-1 rule: a tool is live
only if its `automation` block is ENABLED (a disabled calendar yields no `calendar`
tool — structural denial). That gate is applied here at build time.
"""

from __future__ import annotations

from typing import Optional

from contracts.config_schema.schema import AgentConfig
from contracts.tool_registry.interface import (
    Connection,
    RegistryTool,
    Timing,
    ToolContext,
    ToolHandler,
)
from backend.tool_registry.catalog import DEFAULT_CATALOG
from backend.tool_registry.connections import ConnectionStore
from backend.tool_registry.credentials import EncryptedCredentialStore
from backend.tool_registry.errors import UnknownTool
from backend.tool_registry.events import EventSink, NullEventSink
from backend.tool_registry.guardrails import GuardrailPolicy
from backend.tool_registry.handlers import CalendarHandler, EmailHandler
from backend.tool_registry.integrations import MockCalendarClient, MockEmailClient


class InMemoryToolRegistry:
    """A concrete `ToolRegistry`: a catalog + wired handlers, scoped to one agent's
    guardrail policy. Connection lookups go through the tenant-scoped store."""

    def __init__(
        self,
        tools: dict[str, RegistryTool],
        handlers: dict[str, ToolHandler],
        connections: ConnectionStore,
    ):
        self._tools = tools
        self._handlers = handlers
        self._connections = connections

    # --- frozen Protocol surface ---
    def list_tools(self, timing: Optional[Timing] = None) -> list[RegistryTool]:
        tools = list(self._tools.values())
        if timing is not None:
            tools = [t for t in tools if t.timing == timing]
        return tools

    def get(self, name: str) -> Optional[RegistryTool]:
        return self._tools.get(name)

    def handler_for(self, name: str) -> ToolHandler:
        handler = self._handlers.get(name)
        if handler is None:
            raise UnknownTool(f"No such tool: {name}", tool=name)
        return handler

    # --- registry-owned context resolution (contract: the registry resolves this) ---
    def resolve_context(
        self,
        name: str,
        tenant_id: str,
        *,
        campaign_id: Optional[str] = None,
        lead_id: Optional[str] = None,
    ) -> ToolContext:
        """Build the `ToolContext` for a call: WHO + WHICH connection. The connection
        is the tenant's own connection for the tool's provider (may be None if the
        provider needs none). Cross-tenant is impossible — the store filters by
        tenant in code."""
        tool = self.get(name)
        if tool is None:
            raise UnknownTool(f"No such tool: {name}", tool=name)
        conn: Optional[Connection] = None
        if tool.provider is not None:
            conn = self._connections.for_provider(tenant_id, tool.provider)
        return ToolContext(
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            lead_id=lead_id,
            connection=conn,
        )

    async def execute(
        self,
        name: str,
        args: dict,
        tenant_id: str,
        *,
        campaign_id: Optional[str] = None,
        lead_id: Optional[str] = None,
    ) -> dict:
        """Resolve context then run the handler. Convenience for callers and tests;
        the handler still enforces guardrails and token resolution."""
        handler = self.handler_for(name)
        ctx = self.resolve_context(
            name, tenant_id, campaign_id=campaign_id, lead_id=lead_id
        )
        return await handler.execute(args, ctx)


def _with_template_enum(tool: RegistryTool, template_ids: tuple[str, ...]) -> RegistryTool:
    """Return a copy of the email tool whose `template_id` param enum is the agent's
    concrete approved ids — the least-privilege schema the model must satisfy."""
    clone = tool.model_copy(deep=True)
    props = clone.params.get("properties", {})
    if "template_id" in props:
        props["template_id"] = {**props["template_id"], "enum": list(template_ids)}
    return clone


def build_registry(
    config: AgentConfig,
    connections: ConnectionStore,
    credentials: EncryptedCredentialStore,
    *,
    sink: Optional[EventSink] = None,
    calendar_client: Optional[MockCalendarClient] = None,
    email_client: Optional[MockEmailClient] = None,
) -> InMemoryToolRegistry:
    """Build the registry an agent actually exposes, per its enabled automation and
    distilled guardrails. Only ENABLED automation blocks yield a live tool."""
    sink = sink or NullEventSink()
    policy = GuardrailPolicy.from_config(config)
    catalog = {t.name: t for t in DEFAULT_CATALOG}

    tools: dict[str, RegistryTool] = {}
    handlers: dict[str, ToolHandler] = {}

    # calendar — live only if enabled (structural denial, as in Phase 1).
    if config.automation.calendar.enabled and "calendar" in catalog:
        tools["calendar"] = catalog["calendar"]
        handlers["calendar"] = CalendarHandler(
            policy, credentials, sink, client=calendar_client
        )

    # email — live only if enabled; the param enum is narrowed to approved ids.
    if config.automation.email.enabled and "email" in catalog:
        tools["email"] = _with_template_enum(catalog["email"], policy.approved_template_ids)
        handlers["email"] = EmailHandler(
            policy, credentials, sink, client=email_client
        )

    return InMemoryToolRegistry(tools, handlers, connections)
