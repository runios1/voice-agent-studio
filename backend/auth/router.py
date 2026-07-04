"""FastAPI router for the Google sign-in flow — mounted at /api/auth:

    GET  /auth/google/login     redirect the browser to Google
    GET  /auth/google/callback  exchange the code, set the session cookie, 302 into the app
    GET  /auth/me               who's signed in (401 if not)
    POST /auth/logout           clear the session

Same shape as `tool_registry/connections_router.py`'s OAuth callback: the state is
pinned server-side at `login` and only ever read back at `callback`, never trusted
from the request.
"""

from __future__ import annotations

import secrets
import time
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from backend.auth.google_login import GoogleLoginError, GoogleLoginProvider
from backend.auth.session import SESSION_COOKIE, cookie_secure
from backend.auth.store import AuthStore

_STATE_TTL_SECONDS = 600  # 10 minutes to complete the round trip to Google and back
_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days, matches DEFAULT_SESSION_TTL


def create_router(
    store: AuthStore,
    provider: GoogleLoginProvider,
    *,
    redirect_uri: str,
    app_redirect_url: str = "/",
    on_login: Optional[Callable[[str], None]] = None,
) -> APIRouter:
    """`redirect_uri` is the backend's OWN callback URL (must match what's
    registered with the Google OAuth client); `app_redirect_url` is where the
    browser bounces back to in the app once login has completed. `on_login`
    (optional) fires with the user id right after a session is created — e.g. to
    seed dev tool-connection placeholders for a brand-new real user."""
    router = APIRouter()
    # state -> expiry (monotonic clock); single-use, swept lazily on each new login.
    pending: dict[str, float] = {}

    def _new_state() -> str:
        now = time.monotonic()
        for s, exp in list(pending.items()):
            if exp < now:
                del pending[s]
        state = secrets.token_urlsafe(24)
        pending[state] = now + _STATE_TTL_SECONDS
        return state

    def _consume_state(state: str) -> bool:
        exp = pending.pop(state, None)
        return exp is not None and exp >= time.monotonic()

    @router.get("/auth/google/login")
    def login():
        state = _new_state()
        return RedirectResponse(url=provider.authorization_url(redirect_uri, state))

    @router.get("/auth/google/callback")
    async def callback(code: str = Query(...), state: str = Query(...)):
        if not _consume_state(state):
            return RedirectResponse(url=f"{app_redirect_url}?login=error")
        try:
            identity = await provider.exchange_identity(code, redirect_uri)
        except GoogleLoginError:
            return RedirectResponse(url=f"{app_redirect_url}?login=error")
        user = store.get_or_create_user(
            identity.sub, identity.email, identity.name, identity.picture
        )
        if on_login is not None:
            on_login(user.id)
        token = store.create_session(user.id)
        resp = RedirectResponse(url=app_redirect_url)
        resp.set_cookie(
            SESSION_COOKIE,
            token,
            httponly=True,
            samesite="lax",
            secure=cookie_secure(),
            path="/",
            max_age=_COOKIE_MAX_AGE_SECONDS,
        )
        return resp

    @router.get("/auth/me")
    def me(request: Request):
        token = request.cookies.get(SESSION_COOKIE)
        user_id = store.get_session_user(token) if token else None
        if not user_id:
            raise HTTPException(status_code=401, detail="Not authenticated.")
        user = store.get_user(user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="Not authenticated.")
        return {"id": user.id, "email": user.email, "name": user.name, "picture": user.picture}

    @router.post("/auth/logout")
    def logout(request: Request, response: Response):
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            store.delete_session(token)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    return router
