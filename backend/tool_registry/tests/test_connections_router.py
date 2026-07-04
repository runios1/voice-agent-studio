"""HTTP surface over the OAuth connect flow (`contracts/connections_http`) — P3-1."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from backend.tool_registry.connections import ConnectionManager, ConnectionStore
from backend.tool_registry.connections_router import create_app
from backend.tool_registry.credentials import EncryptedCredentialStore
from backend.tool_registry.oauth import FakeOAuthProvider

from .conftest import CALENDAR_PROVIDER, EMAIL_PROVIDER, OTHER, TENANT

H = {"X-Tenant-Id": TENANT}


@pytest.fixture
def store() -> ConnectionStore:
    return ConnectionStore()


@pytest.fixture
def manager(credentials: EncryptedCredentialStore, store: ConnectionStore) -> ConnectionManager:
    providers = {
        CALENDAR_PROVIDER: FakeOAuthProvider(CALENDAR_PROVIDER),
        EMAIL_PROVIDER: FakeOAuthProvider(EMAIL_PROVIDER),
    }
    return ConnectionManager(providers, store, credentials)


@pytest.fixture
def client(manager, store) -> TestClient:
    return TestClient(create_app(manager, store, app_redirect_url="https://app.test/"))


def test_list_connections_shows_the_whole_catalog_disconnected_by_default(client):
    r = client.get("/api/connections", headers=H)
    assert r.status_code == 200
    body = r.json()["connections"]
    assert {c["provider"] for c in body} == {CALENDAR_PROVIDER, EMAIL_PROVIDER}
    assert all(c["connected"] is False for c in body)


def test_missing_auth_header_is_401(client):
    assert client.get("/api/connections").status_code == 401


def test_authorize_returns_a_url_with_state(client):
    r = client.post(f"/api/connections/{CALENDAR_PROVIDER}/authorize", headers=H)
    assert r.status_code == 200
    url = r.json()["authorization_url"]
    q = parse_qs(urlparse(url).query)
    assert q["state"][0]


def test_unknown_provider_authorize_is_rejected(client):
    r = client.post("/api/connections/not-a-provider/authorize", headers=H)
    assert r.status_code >= 400


def test_full_connect_flow_then_list_shows_connected(client):
    auth_url = client.post(f"/api/connections/{CALENDAR_PROVIDER}/authorize", headers=H).json()[
        "authorization_url"
    ]
    state = parse_qs(urlparse(auth_url).query)["state"][0]

    cb = client.get(
        "/api/oauth/callback",
        params={"code": "auth-code-1", "state": state},
        follow_redirects=False,
    )
    assert cb.status_code in (302, 307)
    assert cb.headers["location"].startswith("https://app.test/")
    assert "connected=ok" in cb.headers["location"]

    body = client.get("/api/connections", headers=H).json()["connections"]
    entry = next(c for c in body if c["provider"] == CALENDAR_PROVIDER)
    assert entry["connected"] is True
    assert entry["connection_ref"]  # opaque ref present, never the token itself


def test_successful_connect_fires_on_connected_hook_with_tenant_and_provider(manager, store):
    fired: list[tuple[str, str]] = []
    client = TestClient(
        create_app(
            manager,
            store,
            app_redirect_url="https://app.test/",
            on_connected=lambda tenant, provider: fired.append((tenant, provider)),
        )
    )
    auth_url = client.post(f"/api/connections/{CALENDAR_PROVIDER}/authorize", headers=H).json()[
        "authorization_url"
    ]
    state = parse_qs(urlparse(auth_url).query)["state"][0]
    client.get("/api/oauth/callback", params={"code": "c", "state": state}, follow_redirects=False)

    assert fired == [(TENANT, CALENDAR_PROVIDER)]


def test_a_raising_on_connected_hook_never_breaks_the_connect(manager, store):
    def boom(tenant, provider):
        raise RuntimeError("downstream blew up")

    client = TestClient(
        create_app(manager, store, app_redirect_url="https://app.test/", on_connected=boom)
    )
    auth_url = client.post(f"/api/connections/{CALENDAR_PROVIDER}/authorize", headers=H).json()[
        "authorization_url"
    ]
    state = parse_qs(urlparse(auth_url).query)["state"][0]
    cb = client.get(
        "/api/oauth/callback", params={"code": "c", "state": state}, follow_redirects=False
    )
    # the connect still succeeds; the hook failure is swallowed
    assert cb.status_code in (302, 307)
    assert "connected=ok" in cb.headers["location"]


def test_callback_with_bad_state_redirects_with_error(client):
    cb = client.get(
        "/api/oauth/callback",
        params={"code": "x", "state": "not-a-real-state"},
        follow_redirects=False,
    )
    assert cb.status_code in (302, 307)
    assert "connected=error" in cb.headers["location"]


def test_disconnect_revokes_and_is_tenant_scoped(client):
    auth_url = client.post(f"/api/connections/{EMAIL_PROVIDER}/authorize", headers=H).json()[
        "authorization_url"
    ]
    state = parse_qs(urlparse(auth_url).query)["state"][0]
    client.get("/api/oauth/callback", params={"code": "c", "state": state})

    # Bob's disconnect of the same provider name is a no-op on Alice's connection.
    bob = {"X-Tenant-Id": OTHER}
    client.delete(f"/api/connections/{EMAIL_PROVIDER}", headers=bob)
    still_there = client.get("/api/connections", headers=H).json()["connections"]
    assert next(c for c in still_there if c["provider"] == EMAIL_PROVIDER)["connected"] is True

    client.delete(f"/api/connections/{EMAIL_PROVIDER}", headers=H)
    gone = client.get("/api/connections", headers=H).json()["connections"]
    assert next(c for c in gone if c["provider"] == EMAIL_PROVIDER)["connected"] is False


def test_state_is_never_reusable_across_a_second_callback(client):
    auth_url = client.post(f"/api/connections/{CALENDAR_PROVIDER}/authorize", headers=H).json()[
        "authorization_url"
    ]
    state = parse_qs(urlparse(auth_url).query)["state"][0]
    client.get("/api/oauth/callback", params={"code": "c1", "state": state})
    replay = client.get(
        "/api/oauth/callback", params={"code": "c2", "state": state}, follow_redirects=False
    )
    assert "connected=error" in replay.headers["location"]
