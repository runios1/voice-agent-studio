"""Per-tenant OAuth — the connect flow behind every `Connection`.

Standard authorization-code flow, split into the two steps a web UI drives:

  1. `authorization_url(...)` — where we send the tenant's browser to grant access.
     Pure string building; no network. Carries a signed/opaque `state` so the
     callback can't be forged and the tenant is pinned.
  2. `exchange_code(...)` — swap the returned `code` for tokens at the provider's
     token endpoint. This is the only step that talks to the provider; it is done
     through an INJECTED async `http_post` callable so:
       * CI needs no network and no real client secret (a `FakeOAuthProvider` and a
         stub poster stand in), and
       * the real Google path is a thin, swappable adapter (Vertex-style migration
         posture, D9) — the same shape, real endpoint.

Client secrets come from the environment, never the repo, never a model's context
(conventions). The tokens this returns are handed straight to the encrypted,
tenant-scoped `CredentialStore` — they do not linger.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Protocol
from urllib.parse import urlencode

from backend.tool_registry.errors import ProviderError

# An injectable async HTTP POST: (url, form_data) -> parsed JSON dict.
HttpPost = Callable[[str, dict], Awaitable[dict]]


@dataclass(frozen=True)
class ProviderSpec:
    """Static OAuth endpoints + client config for one provider."""

    provider: str
    auth_endpoint: str
    token_endpoint: str
    client_id_env: str
    client_secret_env: str


# Where each provider's OAuth lives. Client id/secret are read from the env by name.
PROVIDER_SPECS: dict[str, ProviderSpec] = {
    "google_calendar": ProviderSpec(
        provider="google_calendar",
        auth_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
        token_endpoint="https://oauth2.googleapis.com/token",
        client_id_env="GOOGLE_OAUTH_CLIENT_ID",
        client_secret_env="GOOGLE_OAUTH_CLIENT_SECRET",
    ),
    "gmail": ProviderSpec(
        provider="gmail",
        auth_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
        token_endpoint="https://oauth2.googleapis.com/token",
        client_id_env="GOOGLE_OAUTH_CLIENT_ID",
        client_secret_env="GOOGLE_OAUTH_CLIENT_SECRET",
    ),
}


@dataclass
class TokenBundle:
    """What a successful exchange yields. Fed directly to the credential store."""

    access_token: str
    refresh_token: Optional[str] = None
    scopes: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.scopes is None:
            self.scopes = []


class OAuthProvider(Protocol):
    """The two-step connect flow for one provider."""

    provider: str

    def authorization_url(
        self, redirect_uri: str, scopes: list[str], state: str
    ) -> str: ...

    async def exchange_code(
        self, code: str, redirect_uri: str
    ) -> TokenBundle: ...


class GoogleOAuthProvider:
    """Real Google authorization-code flow. Network happens only in `exchange_code`,
    through the injected `http_post` (so it is unit-testable and CI-safe)."""

    def __init__(self, spec: ProviderSpec, http_post: HttpPost):
        self.provider = spec.provider
        self._spec = spec
        self._http_post = http_post

    def _client_id(self) -> str:
        cid = os.environ.get(self._spec.client_id_env)
        if not cid:
            raise ProviderError("OAuth client id is not configured.")
        return cid

    def _client_secret(self) -> str:
        secret = os.environ.get(self._spec.client_secret_env)
        if not secret:
            raise ProviderError("OAuth client secret is not configured.")
        return secret

    def authorization_url(
        self, redirect_uri: str, scopes: list[str], state: str
    ) -> str:
        params = {
            "client_id": self._client_id(),
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
            "access_type": "offline",   # ask for a refresh token
            "prompt": "consent",
        }
        return f"{self._spec.auth_endpoint}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenBundle:
        payload = {
            "code": code,
            "client_id": self._client_id(),
            "client_secret": self._client_secret(),
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        try:
            data = await self._http_post(self._spec.token_endpoint, payload)
        except Exception:  # noqa: BLE001 - never leak provider internals to callers
            raise ProviderError("Token exchange with the provider failed.")
        access = data.get("access_token")
        if not access:
            raise ProviderError("Provider did not return an access token.")
        scope_str = data.get("scope", "")
        return TokenBundle(
            access_token=access,
            refresh_token=data.get("refresh_token"),
            scopes=scope_str.split() if scope_str else [],
        )


class FakeOAuthProvider:
    """CI/dev provider: no network, no secrets. `authorization_url` is a real-shaped
    string; `exchange_code` mints a deterministic fake token for the code."""

    def __init__(self, provider: str):
        self.provider = provider

    def authorization_url(
        self, redirect_uri: str, scopes: list[str], state: str
    ) -> str:
        params = {
            "client_id": "fake-client-id",
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
        }
        return f"https://oauth.test/{self.provider}/auth?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenBundle:
        if not code:
            raise ProviderError("Missing authorization code.")
        return TokenBundle(
            access_token=f"fake-access-{self.provider}-{code}",
            refresh_token=f"fake-refresh-{self.provider}-{code}",
            scopes=[],
        )
