"""Google sign-in — the login flow (WHO the user is), separate from
`tool_registry/oauth.py`'s per-tenant tool-connect flow (WHAT a tenant grants
access to). Same authorization-code shape, but the exchange is followed by a
userinfo fetch (identity, not an API scope grant, is the point of this one).

State is a random, single-use, server-pinned nonce (never a client-supplied value)
so the callback can't be forged/replayed — same posture as
`tool_registry/connections.py`'s `begin_connect`/`complete_connect`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Protocol
from urllib.parse import urlencode

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v3/userinfo"
LOGIN_SCOPES = ["openid", "email", "profile"]

# (url, form_data) -> parsed JSON dict
HttpPost = Callable[[str, dict], Awaitable[dict]]
# (url, bearer_token) -> parsed JSON dict
HttpGet = Callable[[str, str], Awaitable[dict]]


class GoogleLoginError(Exception):
    pass


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str
    picture: Optional[str]


class GoogleLoginProvider(Protocol):
    def authorization_url(self, redirect_uri: str, state: str) -> str: ...

    async def exchange_identity(self, code: str, redirect_uri: str) -> GoogleIdentity: ...


class RealGoogleLoginProvider:
    """The real Google authorization-code + userinfo flow. Network happens only in
    `exchange_identity`, through injected `http_post`/`http_get` (unit-testable, no
    real client secret needed in CI — mirrors `tool_registry/oauth.py`)."""

    def __init__(self, http_post: HttpPost, http_get: HttpGet):
        self._http_post = http_post
        self._http_get = http_get

    def _client_id(self) -> str:
        cid = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
        if not cid:
            raise GoogleLoginError("Google OAuth client id is not configured.")
        return cid

    def _client_secret(self) -> str:
        secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
        if not secret:
            raise GoogleLoginError("Google OAuth client secret is not configured.")
        return secret

    def authorization_url(self, redirect_uri: str, state: str) -> str:
        params = {
            "client_id": self._client_id(),
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(LOGIN_SCOPES),
            "state": state,
            "prompt": "select_account",
        }
        return f"{AUTH_ENDPOINT}?{urlencode(params)}"

    async def exchange_identity(self, code: str, redirect_uri: str) -> GoogleIdentity:
        payload = {
            "code": code,
            "client_id": self._client_id(),
            "client_secret": self._client_secret(),
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        try:
            token_data = await self._http_post(TOKEN_ENDPOINT, payload)
        except GoogleLoginError:
            raise
        except Exception:  # noqa: BLE001 - never leak provider internals to callers
            raise GoogleLoginError("Token exchange with Google failed.")
        access_token = token_data.get("access_token")
        if not access_token:
            raise GoogleLoginError("Google did not return an access token.")
        try:
            info = await self._http_get(USERINFO_ENDPOINT, access_token)
        except Exception:  # noqa: BLE001
            raise GoogleLoginError("Fetching the Google profile failed.")
        sub = info.get("sub")
        email = info.get("email")
        if not sub or not email:
            raise GoogleLoginError("Google profile is missing sub/email.")
        return GoogleIdentity(
            sub=sub, email=email, name=info.get("name") or email, picture=info.get("picture")
        )


class FakeGoogleLoginProvider:
    """CI/dev provider: no network, no secrets. Mints a deterministic identity from
    the fake `code` so tests can drive the whole login flow without Google."""

    def authorization_url(self, redirect_uri: str, state: str) -> str:
        # No real consent screen exists in dev/CI, so bounce STRAIGHT back to our own
        # callback with a canned code: a browser "Sign in" then completes in one hop as a
        # stable dev identity (no Google, no unreachable accounts.test page). Tests drive
        # the callback directly and only read `state` off this URL, so the self-completing
        # shape doesn't change their behavior. Only ever used when GOOGLE_OAUTH_CLIENT_ID
        # is unset (real deployments always use RealGoogleLoginProvider).
        return f"{redirect_uri}?{urlencode({'code': 'dev', 'state': state})}"

    async def exchange_identity(self, code: str, redirect_uri: str) -> GoogleIdentity:
        if not code:
            raise GoogleLoginError("Missing authorization code.")
        return GoogleIdentity(
            sub=f"fake-sub-{code}",
            email=f"{code}@example.test",
            name=f"Test User {code}",
            picture=None,
        )
