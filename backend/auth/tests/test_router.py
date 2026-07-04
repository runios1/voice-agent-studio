"""HTTP surface over the Google sign-in flow — mirrors
`tool_registry/tests/test_connections_router.py`'s style for the OAuth-callback
shape, but the flow is identity (a session cookie), not a per-tenant tool grant."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth.google_login import FakeGoogleLoginProvider
from backend.auth.router import create_router
from backend.auth.session import SESSION_COOKIE
from backend.auth.store import InMemoryAuthStore

REDIRECT_URI = "http://localhost:8000/api/auth/google/callback"
APP_URL = "https://app.test/"


@pytest.fixture
def store() -> InMemoryAuthStore:
    return InMemoryAuthStore()


@pytest.fixture
def logged_in_users() -> list[str]:
    return []


@pytest.fixture
def client(store, logged_in_users) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_router(
            store,
            FakeGoogleLoginProvider(),
            redirect_uri=REDIRECT_URI,
            app_redirect_url=APP_URL,
            on_login=logged_in_users.append,
        ),
        prefix="/api",
    )
    return TestClient(app)


def _login_state(client: TestClient) -> str:
    r = client.get("/api/auth/google/login", follow_redirects=False)
    assert r.status_code in (302, 307)
    q = parse_qs(urlparse(r.headers["location"]).query)
    return q["state"][0]


def test_me_without_a_session_is_401(client):
    assert client.get("/api/auth/me").status_code == 401


def test_login_redirects_with_a_state(client):
    state = _login_state(client)
    assert state


def test_callback_sets_a_session_cookie_and_redirects_to_the_app(client):
    state = _login_state(client)
    r = client.get(
        f"/api/auth/google/callback?code=abc&state={state}", follow_redirects=False
    )
    assert r.status_code in (302, 307)
    assert r.headers["location"] == APP_URL
    assert SESSION_COOKIE in r.cookies


def test_me_reflects_the_signed_in_user(client):
    state = _login_state(client)
    client.get(f"/api/auth/google/callback?code=abc&state={state}")
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "abc@example.test"


def test_on_login_hook_fires_with_the_user_id(client, logged_in_users):
    state = _login_state(client)
    client.get(f"/api/auth/google/callback?code=abc&state={state}")
    me = client.get("/api/auth/me").json()
    assert logged_in_users == [me["id"]]


def test_returning_user_gets_the_same_id(client):
    state = _login_state(client)
    client.get(f"/api/auth/google/callback?code=abc&state={state}")
    first = client.get("/api/auth/me").json()["id"]

    client.cookies.clear()
    state2 = _login_state(client)
    client.get(f"/api/auth/google/callback?code=abc&state={state2}")
    second = client.get("/api/auth/me").json()["id"]
    assert first == second


def test_state_cannot_be_replayed(client):
    state = _login_state(client)
    client.get(f"/api/auth/google/callback?code=abc&state={state}")
    r = client.get(
        f"/api/auth/google/callback?code=abc&state={state}", follow_redirects=False
    )
    assert r.headers["location"] == f"{APP_URL}?login=error"


def test_unknown_state_is_rejected(client):
    r = client.get(
        "/api/auth/google/callback?code=abc&state=not-a-real-state", follow_redirects=False
    )
    assert r.headers["location"] == f"{APP_URL}?login=error"


def test_logout_clears_the_session(client):
    state = _login_state(client)
    client.get(f"/api/auth/google/callback?code=abc&state={state}")
    assert client.get("/api/auth/me").status_code == 200

    r = client.post("/api/auth/logout")
    assert r.status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_second_client_without_the_cookie_is_not_authenticated(client, store):
    state = _login_state(client)
    client.get(f"/api/auth/google/callback?code=abc&state={state}")

    app = FastAPI()
    app.include_router(
        create_router(
            store, FakeGoogleLoginProvider(), redirect_uri=REDIRECT_URI, app_redirect_url=APP_URL
        ),
        prefix="/api",
    )
    other_client = TestClient(app)
    assert other_client.get("/api/auth/me").status_code == 401
