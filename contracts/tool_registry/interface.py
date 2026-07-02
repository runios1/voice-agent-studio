"""
FROZEN CONTRACT (Phase 2) — Tool registry interface
===================================================

Generalizes Phase 1's `backend/runtime_loop/tools.build_tools()` — which hard-codes
`if calendar.enabled -> book_meeting`, `if email.enabled -> send_email` — into a
curated **registry** (P2-D4). The registry IS the platform capability surface and
the answer to the four-way triage (D13): "supported" == "in the registry."

Invariants carried over from Phase 1 (D-security):
  * **capability == an exposed function, nothing more.** A tool exists only if it's
    in the registry AND its automation block is enabled. No `offer_discount`, no
    free-composed URL/body — parameter schemas are least-privilege.
  * every tool runs against a **per-tenant connection** (encrypted, tenant-scoped);
    never a shared credential.

The registry maps a capability NAME (matching an `automation` block, e.g.
"calendar", "email") to a RegistryTool. No change to the frozen config schema is
required — automation blocks reference tools by name. This is a STUB: signatures +
docstrings are the contract; handlers live in P2-3.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional, Protocol

from pydantic import BaseModel, Field

from contracts.model_wrapper.interface import ToolDef


class Timing(str, Enum):
    IN_CALL = "in_call"      # fast function the voice LLM calls live (D6). Latency-bound.
    POST_CALL = "post_call"  # async orchestration (email/CRM/follow-up), latency-tolerant.


class RegistryTool(BaseModel):
    """A platform-curated capability. `params` is the least-privilege JSON Schema the
    model must satisfy (identical role to Phase-1 ToolDef.parameters). `provider` +
    `required_scopes` drive the OAuth connection needed to run it."""

    name: str                                  # matches an automation block name
    description: str
    timing: Timing
    params: dict[str, Any]                     # least-privilege JSON Schema
    provider: Optional[str] = None             # e.g. "google_calendar", "gmail", "salesforce"
    required_scopes: list[str] = Field(default_factory=list)

    def to_tool_def(self) -> ToolDef:
        """Adapt to the model-facing ToolDef (Phase-1 shape) for in-call exposure."""
        return ToolDef(name=self.name, description=self.description, parameters=self.params)


class Connection(BaseModel):
    """A per-tenant OAuth connection to a provider. Tokens themselves are NEVER in
    this object — they live encrypted behind `CredentialStore`, fetched by ref."""

    tenant_id: str
    provider: str
    connection_ref: str                        # opaque handle into the credential store
    scopes: list[str] = Field(default_factory=list)


class CredentialStore(Protocol):
    """Encrypted, tenant-scoped credential access. Implementation (P2-3) enforces
    that a tenant can only ever reach its own connections (D-security)."""

    async def get_access_token(self, tenant_id: str, connection_ref: str) -> str: ...


class ToolContext(BaseModel, arbitrary_types_allowed=True):
    """Everything a handler needs to act safely: WHO it's acting for and WHICH
    connection. The registry resolves this; a handler never picks its own tenant."""

    tenant_id: str
    campaign_id: Optional[str] = None
    lead_id: Optional[str] = None
    connection: Optional[Connection] = None


class ToolHandler(Protocol):
    """Executes one RegistryTool. Guardrails (business hours, allowlisted domains,
    scope limits) are enforced HERE, in code — the enforcement point (D6/D-security).
    Returns a JSON-serializable result fed back to the model (in-call) or workflow."""

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]: ...


class ToolRegistry(Protocol):
    """The catalog. Curated, not self-serve — new tools are a platform roadmap item,
    which is what keeps it a guardrail surface (P2-D4)."""

    def list_tools(self, timing: Optional[Timing] = None) -> list[RegistryTool]: ...
    def get(self, name: str) -> Optional[RegistryTool]: ...
    def handler_for(self, name: str) -> ToolHandler: ...
