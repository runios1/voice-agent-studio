"""Per-tenant OAuth connect flow + tenant-scoped connection store."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from backend.tool_registry.connections import ConnectionManager, ConnectionStore
from backend.tool_registry.errors import ProviderError, TenantAccessDenied

from .conftest import CALENDAR_PROVIDER, EMAIL_PROVIDER, OTHER, REDIRECT, TENANT


def _begin(manager: ConnectionManager, tenant=TENANT, provider=CALENDAR_PROVIDER):
    url = manager.begin_connect(tenant, provider, ["scope.a"], REDIRECT)
    state = parse_qs(urlparse(url).query)["state"][0]
    return url, state


def test_begin_connect_returns_auth_url_with_state(manager: ConnectionManager):
    url, state = _begin(manager)
    q = parse_qs(urlparse(url).query)
    assert q["redirect_uri"][0] == REDIRECT
    assert q["response_type"][0] == "code"
    assert state  # opaque, present


async def test_complete_connect_stores_encrypted_token_and_connection(
    manager: ConnectionManager, connections: ConnectionStore, credentials
):
    _, state = _begin(manager)
    conn = await manager.complete_connect(state, code="auth-code-xyz")

    assert conn.tenant_id == TENANT
    assert conn.provider == CALENDAR_PROVIDER
    # The connection only carries an opaque ref — never the token.
    assert "auth-code-xyz" not in conn.connection_ref
    # ...and the token is retrievable (decrypts) for the owning tenant.
    tok = await credentials.get_access_token(TENANT, conn.connection_ref)
    assert tok.startswith("fake-access-")
    # The store now resolves it by provider, scoped to the tenant.
    assert connections.for_provider(TENANT, CALENDAR_PROVIDER).connection_ref == conn.connection_ref


async def test_forged_or_replayed_state_is_rejected(manager: ConnectionManager):
    _, state = _begin(manager)
    with pytest.raises(ProviderError):
        await manager.complete_connect("not-the-state", code="x")
    # State is single-use: consuming it once removes it.
    await manager.complete_connect(state, code="x")
    with pytest.raises(ProviderError):
        await manager.complete_connect(state, code="x")


async def test_state_pins_tenant_not_the_callback(manager: ConnectionManager):
    # Bob cannot make a connect he didn't start resolve to himself — the tenant comes
    # from the pinned state, which only Alice's begin_connect created.
    _, alice_state = _begin(manager, tenant=TENANT)
    conn = await manager.complete_connect(alice_state, code="c")
    assert conn.tenant_id == TENANT  # never OTHER


def test_connection_store_is_tenant_scoped(connections: ConnectionStore):
    from contracts.tool_registry.interface import Connection

    connections.add(Connection(tenant_id=TENANT, provider=CALENDAR_PROVIDER, connection_ref="a"))
    # Bob sees nothing; Alice sees hers.
    assert connections.for_provider(OTHER, CALENDAR_PROVIDER) is None
    assert connections.get(OTHER, "a") is None
    assert connections.list(OTHER) == []
    assert connections.get(TENANT, "a").connection_ref == "a"


async def test_disconnect_revokes_credential_and_record(
    manager: ConnectionManager, connections: ConnectionStore, credentials
):
    _, state = _begin(manager, provider=EMAIL_PROVIDER)
    conn = await manager.complete_connect(state, code="c")
    manager.disconnect(TENANT, conn.connection_ref)
    assert connections.for_provider(TENANT, EMAIL_PROVIDER) is None
    with pytest.raises(TenantAccessDenied):
        await credentials.get_access_token(TENANT, conn.connection_ref)
