"""In-call tool layer — registry-driven, capability == an enabled function.

Phase 1 hard-coded `if calendar.enabled -> book_meeting` in
`backend/runtime_loop/tools.build_tools`. Phase 2 keeps the SAME load-bearing rule
(D-security: a tool exists only if its automation block is ENABLED) but sources the
tool definitions from the frozen tool registry (P2-D4) instead of an `if` ladder:

  exposed IN_CALL tool  ⇔  registry.get(name).timing == IN_CALL
                          AND config.automation.<name>.enabled is True

So a disabled calendar yields no `book_meeting` — there is physically no function for
the voice model to call. The registry's `RegistryTool.to_tool_def()` gives the exact
least-privilege `ToolDef` the model sees (same shape as Phase 1).

`ToolContext` is resolved HERE, in code, from the call's correlation ids — never from
the model (a handler must never pick its own tenant, D-security). The per-tenant
`Connection` is resolved by the registry/handler in P2-3; we pass tenant/campaign/lead
scope and leave `connection=None` for the registry to fill.
"""

from __future__ import annotations

from contracts.config_schema.schema import AgentConfig
from contracts.model_wrapper.interface import ToolDef
from contracts.tool_registry.interface import (
    RegistryTool,
    Timing,
    ToolContext,
    ToolRegistry,
)
from contracts.voice_runtime.interface import CallSession


def enabled_in_call_tools(config: AgentConfig, registry: ToolRegistry) -> list[RegistryTool]:
    """The registry tools this agent may use live: IN_CALL timing AND a matching
    automation block that is enabled. Unknown names or disabled blocks yield nothing
    (structural denial)."""
    out: list[RegistryTool] = []
    for tool in registry.list_tools(timing=Timing.IN_CALL):
        block = getattr(config.automation, tool.name, None)
        if block is not None and getattr(block, "enabled", False):
            out.append(tool)
    return out


def build_tool_defs(config: AgentConfig, registry: ToolRegistry) -> list[ToolDef]:
    """The least-privilege `ToolDef`s handed to the voice model — exactly the enabled
    IN_CALL registry tools, adapted via `RegistryTool.to_tool_def()`."""
    return [t.to_tool_def() for t in enabled_in_call_tools(config, registry)]


def context_for(session: CallSession) -> ToolContext:
    """Resolve the `ToolContext` from the call's correlation ids, in code. `connection`
    is left for the registry/handler (P2-3) to resolve per-tenant — the runtime never
    hands a handler a credential or a tenant it chose itself."""
    return ToolContext(
        tenant_id=session.tenant_id,
        campaign_id=session.campaign_id,
        lead_id=session.lead_id,
    )
