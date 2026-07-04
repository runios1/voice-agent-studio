"""The session cookie — an opaque, server-side-revocable lookup key, never a
signed client claim. `build_current_user_dependency` is the ONE real auth
dependency; the integration layer overrides every workstream's mocked
`current_user`/`current_tenant` dependency with it. Each of those already enforces
tenant isolation in code and documents this exact swap ("a real session dep raises
401 here") — only the id *source* changes, no route changes.
"""

from __future__ import annotations

import os

from fastapi import HTTPException, Request

from backend.auth.store import AuthStore

SESSION_COOKIE = "vas_session"


def cookie_secure() -> bool:
    """Off by default so the cookie works over plain http://localhost in dev;
    set COOKIE_SECURE=true once served over https in production."""
    return os.getenv("COOKIE_SECURE", "false").lower() == "true"


def build_current_user_dependency(store: AuthStore):
    def current_user_id(request: Request) -> str:
        token = request.cookies.get(SESSION_COOKIE)
        user_id = store.get_session_user(token) if token else None
        if not user_id:
            raise HTTPException(status_code=401, detail="Not authenticated.")
        return user_id

    return current_user_id
