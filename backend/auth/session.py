"""The session cookie — an opaque, server-side-revocable lookup key, never a
signed client claim. `build_current_user_dependency` is the ONE real auth
dependency; the integration layer overrides every workstream's mocked
`current_user`/`current_tenant` dependency with it. Each of those already enforces
tenant isolation in code and documents this exact swap ("a real session dep raises
401 here") — only the id *source* changes, no route changes.
"""

from __future__ import annotations

import os

from fastapi import HTTPException
from starlette.requests import HTTPConnection

from backend.auth.store import AuthStore

SESSION_COOKIE = "vas_session"


def cookie_secure() -> bool:
    """Off by default so the cookie works over plain http://localhost in dev;
    set COOKIE_SECURE=true once served over https in production."""
    return os.getenv("COOKIE_SECURE", "false").lower() == "true"


def build_current_user_dependency(store: AuthStore, *, fallback_user_id: str | None = None):
    # Typed as HTTPConnection (the shared base of Request AND WebSocket) so the SAME
    # dependency authenticates both HTTP routes and WebSocket routes. A `Request`-typed
    # dep is never injected on a WS route, which broke every authed WS (e.g. the live
    # preview) with a missing-argument TypeError.
    #
    # `fallback_user_id` is the "open"/demo posture: with no valid session, resolve to a
    # shared public user instead of raising 401. A real session still wins (a signed-in
    # user gets their OWN id → their own isolated workspace), so login stays meaningful
    # even when it isn't required. Left None (the default) = login required, as before.
    def current_user_id(conn: HTTPConnection) -> str:
        token = conn.cookies.get(SESSION_COOKIE)
        user_id = store.get_session_user(token) if token else None
        if not user_id:
            if fallback_user_id is not None:
                return fallback_user_id
            raise HTTPException(status_code=401, detail="Not authenticated.")
        return user_id

    return current_user_id
