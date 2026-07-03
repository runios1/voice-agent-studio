"""P2-3 — Tool registry + integrations.

The curated capability surface (P2-D4): a catalog of least-privilege `RegistryTool`s,
per-tenant encrypted OAuth `Connection`s, and `ToolHandler`s that enforce guardrails
in code (the enforcement point, D6/D-security). Consumes the frozen
`contracts/tool_registry` interface; emits to the P2-5 event stream (mocked here).

Public surface:
  * build_registry(config, connections, credentials, ...) -> InMemoryToolRegistry
  * ConnectionManager / ConnectionStore — the per-tenant OAuth connect flow
  * EncryptedCredentialStore — encrypted, tenant-scoped token storage
  * OAuth providers (Google + Fake) and PROVIDER_SPECS
  * the typed ToolError taxonomy
"""

from __future__ import annotations

from backend.tool_registry.catalog import DEFAULT_CATALOG
from backend.tool_registry.connections import ConnectionManager, ConnectionStore
from backend.tool_registry.credentials import EncryptedCredentialStore, generate_key
from backend.tool_registry.errors import (
    GuardrailViolation,
    NotConnected,
    ProviderError,
    TenantAccessDenied,
    ToolError,
    ToolErrorKind,
    UnknownTool,
)
from backend.tool_registry.events import EventSink, InMemoryEventSink, NullEventSink
from backend.tool_registry.guardrails import GuardrailPolicy
from backend.tool_registry.oauth import (
    PROVIDER_SPECS,
    FakeOAuthProvider,
    GoogleOAuthProvider,
    OAuthProvider,
    ProviderSpec,
)
from backend.tool_registry.registry import InMemoryToolRegistry, build_registry

__all__ = [
    "DEFAULT_CATALOG",
    "build_registry",
    "InMemoryToolRegistry",
    "ConnectionManager",
    "ConnectionStore",
    "EncryptedCredentialStore",
    "generate_key",
    "GuardrailPolicy",
    "EventSink",
    "InMemoryEventSink",
    "NullEventSink",
    "OAuthProvider",
    "GoogleOAuthProvider",
    "FakeOAuthProvider",
    "ProviderSpec",
    "PROVIDER_SPECS",
    "ToolError",
    "ToolErrorKind",
    "GuardrailViolation",
    "NotConnected",
    "TenantAccessDenied",
    "UnknownTool",
    "ProviderError",
]
