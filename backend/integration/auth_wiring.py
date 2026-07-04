"""Wiring for the Google sign-in flow — the real network calls + provider
selection, kept out of `backend/auth` itself (same D8/D9 posture as
`integration/runtime.py`'s `_build_oauth_providers`: the driver is lazily
imported/injected so the auth package carries no network cost until a real
login actually happens, and CI never needs a real Google client).
"""

from __future__ import annotations

import os

from backend.auth.google_login import (
    FakeGoogleLoginProvider,
    GoogleLoginProvider,
    RealGoogleLoginProvider,
)


def google_login_configured() -> bool:
    return bool(os.environ.get("GOOGLE_OAUTH_CLIENT_ID"))


async def _httpx_post(url: str, data: dict) -> dict:
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, data=data)
    resp.raise_for_status()
    return resp.json()


async def _httpx_get_bearer(url: str, bearer_token: str) -> dict:
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {bearer_token}"})
    resp.raise_for_status()
    return resp.json()


def build_google_login_provider() -> GoogleLoginProvider:
    """The real Google flow when `GOOGLE_OAUTH_CLIENT_ID` is set, else the
    no-network `FakeGoogleLoginProvider` (dev/CI) — same shape as
    `runtime._build_oauth_providers` for the tool-connect flow."""
    if google_login_configured():
        return RealGoogleLoginProvider(_httpx_post, _httpx_get_bearer)
    return FakeGoogleLoginProvider()
