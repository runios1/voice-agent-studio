"""Typed error taxonomy for the tool registry.

Mirrors the config-gate's approach (`backend/config_gate/errors.py`): a small set of
client-safe rejections, never a stack trace. These are the ways executing a
registry tool can be refused, and they map cleanly onto the security model:

  * GUARDRAIL      — a param violated a code-enforced guardrail (out-of-hours slot,
                     non-allowlisted link domain, unapproved template). This is the
                     "can't-do-it" wall from D-security enforced at the handler.
  * NOT_CONNECTED  — the tenant has no OAuth connection for the tool's provider, so
                     there is nothing to act against. (Structural, not a guess.)
  * TENANT_DENIED  — a request tried to reach a connection that is not the caller's.
                     Denied in code, never by prompt (D-security). Existence of the
                     other tenant's connection is NOT leaked.
  * UNKNOWN_TOOL   — no such tool in the curated catalog (P2-D4).
  * PROVIDER_ERROR — the downstream provider (calendar/email API) failed. Kept
                     generic so provider internals never reach a model's context.

Guardrail trips are also the events auto-pause (P2-6) watches for, so a
`GuardrailViolation` is what a handler raises right after emitting
`GUARDRAIL_TRIPPED`.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class ToolErrorKind(str, Enum):
    GUARDRAIL = "guardrail"
    NOT_CONNECTED = "not_connected"
    TENANT_DENIED = "tenant_denied"
    UNKNOWN_TOOL = "unknown_tool"
    PROVIDER_ERROR = "provider_error"


class ToolError(Exception):
    """A registry rejection with a client-safe message.

    `message` is human-friendly by design and safe to surface; it must never carry
    secrets, tokens, or other tenants' data. `tool` and `param` are optional
    breadcrumbs for logging and for the event payload.
    """

    kind: ToolErrorKind = ToolErrorKind.PROVIDER_ERROR

    def __init__(
        self,
        message: str,
        *,
        tool: Optional[str] = None,
        param: Optional[str] = None,
    ):
        self.message = message
        self.tool = tool
        self.param = param
        super().__init__(f"{self.kind.value}: {message}")

    def to_dict(self) -> dict:
        return {
            "error": {
                "kind": self.kind.value,
                "tool": self.tool,
                "param": self.param,
                "message": self.message,
            }
        }

    # Advisory HTTP status per kind (mirrors config_gate/orchestrator/events errors) —
    # used by any router that surfaces a ToolError directly (e.g. connections_router).
    _STATUS = {
        ToolErrorKind.GUARDRAIL: 422,
        ToolErrorKind.NOT_CONNECTED: 404,
        ToolErrorKind.TENANT_DENIED: 404,  # not-found, never "forbidden" — no leak
        ToolErrorKind.UNKNOWN_TOOL: 404,
        ToolErrorKind.PROVIDER_ERROR: 502,
    }

    @property
    def http_status(self) -> int:
        return self._STATUS.get(self.kind, 400)


class GuardrailViolation(ToolError):
    """A parameter broke a code-enforced guardrail. The enforcement point (D6)."""

    kind = ToolErrorKind.GUARDRAIL


class NotConnected(ToolError):
    """The tenant has no connection for this provider — nothing to act against."""

    kind = ToolErrorKind.NOT_CONNECTED


class TenantAccessDenied(ToolError):
    """A cross-tenant reach was attempted and refused in code (D-security)."""

    kind = ToolErrorKind.TENANT_DENIED

    def __init__(self, message: str = "No such connection.", **kw):
        # Deliberately identical to a genuine miss so existence isn't leaked.
        super().__init__(message, **kw)


class UnknownTool(ToolError):
    """Not in the curated catalog."""

    kind = ToolErrorKind.UNKNOWN_TOOL


class ProviderError(ToolError):
    """The downstream provider failed. Generic on purpose (least context)."""

    kind = ToolErrorKind.PROVIDER_ERROR
