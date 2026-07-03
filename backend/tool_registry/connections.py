"""Per-tenant connections — the connect flow + the tenant-scoped connection store.

A `Connection` (frozen contract) is a per-tenant handle to a provider; the token
itself lives encrypted behind the `CredentialStore` and is reached only by
`connection_ref`. This module owns:

  * `ConnectionStore` — records `Connection`s, scoped by tenant in code. Lookups
    (`get`, `for_provider`, `list`) always take a `tenant_id` and filter by it, so a
    tenant can never enumerate or resolve another tenant's connection.
  * `ConnectionManager` — drives OAuth: `begin_connect` returns the authorization
    URL and stashes the pending `state`; `complete_connect` validates the callback
    `state`, exchanges the code, stores the token ENCRYPTED, and records the
    `Connection`. State pinning ties the callback back to the exact tenant/provider
    that started it, so a forged or replayed callback can't attach a token to the
    wrong tenant.

`connection_ref`s are opaque, unguessable (`secrets.token_urlsafe`), and never
sequential — but note the ref is not the security boundary: the credential store
re-checks the owning tenant on every read (see `credentials.py`). Belt and braces.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Optional

from contracts.tool_registry.interface import Connection
from backend.tool_registry.credentials import EncryptedCredentialStore
from backend.tool_registry.errors import ProviderError
from backend.tool_registry.oauth import OAuthProvider


class ConnectionStore:
    """Tenant-scoped registry of `Connection`s. In-memory (CI/dev); a Postgres
    implementation of the same surface swaps in for production."""

    def __init__(self) -> None:
        # keyed by connection_ref; every read re-filters by tenant.
        self._by_ref: dict[str, Connection] = {}

    def add(self, conn: Connection) -> None:
        self._by_ref[conn.connection_ref] = conn

    def get(self, tenant_id: str, connection_ref: str) -> Optional[Connection]:
        conn = self._by_ref.get(connection_ref)
        if conn is None or conn.tenant_id != tenant_id:
            return None  # cross-tenant or unknown — indistinguishable, no leak
        return conn

    def for_provider(self, tenant_id: str, provider: str) -> Optional[Connection]:
        """The tenant's connection for a provider, if any. Used to resolve the
        connection a tool runs against (most tenants have one per provider)."""
        for conn in self._by_ref.values():
            if conn.tenant_id == tenant_id and conn.provider == provider:
                return conn
        return None

    def list(self, tenant_id: str) -> list[Connection]:
        return [c for c in self._by_ref.values() if c.tenant_id == tenant_id]

    def remove(self, tenant_id: str, connection_ref: str) -> None:
        conn = self._by_ref.get(connection_ref)
        if conn is not None and conn.tenant_id == tenant_id:
            del self._by_ref[connection_ref]


@dataclass
class _Pending:
    tenant_id: str
    provider: str
    scopes: list[str]
    redirect_uri: str


class ConnectionManager:
    """Orchestrates the OAuth connect flow and persists the result. One manager can
    front several providers, keyed by provider name."""

    def __init__(
        self,
        providers: dict[str, OAuthProvider],
        connections: ConnectionStore,
        credentials: EncryptedCredentialStore,
    ):
        self._providers = providers
        self._connections = connections
        self._credentials = credentials
        self._pending: dict[str, _Pending] = {}  # state -> pending connect

    def _provider(self, provider: str) -> OAuthProvider:
        p = self._providers.get(provider)
        if p is None:
            raise ProviderError(f"Unknown provider: {provider}")
        return p

    def begin_connect(
        self, tenant_id: str, provider: str, scopes: list[str], redirect_uri: str
    ) -> str:
        """Start a connect: return the authorization URL the tenant's browser opens.
        A random `state` pins the eventual callback to THIS tenant + provider."""
        oauth = self._provider(provider)
        state = secrets.token_urlsafe(24)
        self._pending[state] = _Pending(tenant_id, provider, list(scopes), redirect_uri)
        return oauth.authorization_url(redirect_uri, scopes, state)

    async def complete_connect(self, state: str, code: str) -> Connection:
        """Finish a connect from the OAuth callback. Validates `state`, exchanges the
        code, stores the token encrypted, and records the tenant-scoped Connection.

        The tenant is taken from the pinned `state`, NEVER from the callback request —
        a forged callback cannot bind a token to a tenant it didn't start for."""
        pending = self._pending.pop(state, None)
        if pending is None:
            raise ProviderError("Unknown or expired OAuth state.")

        oauth = self._provider(pending.provider)
        bundle = await oauth.exchange_code(code, pending.redirect_uri)

        connection_ref = secrets.token_urlsafe(24)
        # Encrypt + store the token first; the Connection only holds the opaque ref.
        self._credentials.put(
            tenant_id=pending.tenant_id,
            connection_ref=connection_ref,
            provider=pending.provider,
            access_token=bundle.access_token,
            refresh_token=bundle.refresh_token,
            scopes=bundle.scopes or pending.scopes,
        )
        conn = Connection(
            tenant_id=pending.tenant_id,
            provider=pending.provider,
            connection_ref=connection_ref,
            scopes=bundle.scopes or pending.scopes,
        )
        self._connections.add(conn)
        return conn

    def disconnect(self, tenant_id: str, connection_ref: str) -> None:
        """Revoke a connection: drop the credential and the Connection record. Both
        are tenant-checked, so a cross-tenant disconnect is a silent no-op."""
        self._credentials.revoke(tenant_id, connection_ref)
        self._connections.remove(tenant_id, connection_ref)
