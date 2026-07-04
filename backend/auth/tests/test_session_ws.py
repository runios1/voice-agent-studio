"""The session dependency must authenticate WebSocket routes, not only HTTP ones — a
`Request`-typed dep is never injected on a WS route (FastAPI passes a WebSocket), which
once broke the live preview WS with a missing-argument TypeError."""

from __future__ import annotations

from fastapi import Depends, FastAPI, WebSocket
from starlette.testclient import TestClient

from backend.auth.session import SESSION_COOKIE, build_current_user_dependency
from backend.auth.store import InMemoryAuthStore


def _app(store):
    dep = build_current_user_dependency(store)
    app = FastAPI()

    @app.get("/http")
    async def http(user: str = Depends(dep)):
        return {"user": user}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket, user: str = Depends(dep)):
        await websocket.accept()
        await websocket.send_text(user)
        await websocket.close()

    return app


def test_valid_session_authenticates_both_http_and_websocket():
    store = InMemoryAuthStore()
    token = store.create_session("user-123")
    client = TestClient(_app(store))
    client.cookies.set(SESSION_COOKIE, token)

    assert client.get("/http").json() == {"user": "user-123"}
    with client.websocket_connect("/ws") as ws:  # would TypeError before the fix
        assert ws.receive_text() == "user-123"


def test_missing_session_rejects_both():
    store = InMemoryAuthStore()
    client = TestClient(_app(store))  # no cookie

    assert client.get("/http").status_code == 401
    import pytest

    with pytest.raises(Exception):  # WS handshake denied (not a crash)
        with client.websocket_connect("/ws"):
            pass
