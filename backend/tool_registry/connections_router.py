"""Thin FastAPI router over the OAuth connect flow — the P3-1 HTTP skin implementing
`contracts/connections_http` exactly (P3-6's "Connect Google Calendar" flow calls this).

Same posture as `events/router.py` / `orchestrator/control_api.py`: this module only
binds HTTP and resolves the authed tenant; all logic (state pinning, code exchange,
encrypted storage) already lives in `ConnectionManager` / `ConnectionStore` /
`EncryptedCredentialStore` (unchanged by this router). The provider catalog + scopes
come from `backend/tool_registry/catalog.py` so this never invents its own list.

AUTH IS MOCKED here exactly like the other Phase-2 routers: `current_tenant` reads
`X-Tenant-Id`. The integrator overrides it with the real session dep; tenant scoping
itself is already enforced in code (`ConnectionStore`/`EncryptedCredentialStore`), so
only the id *source* changes.

The OAuth callback is a browser navigation (no auth header available), so per the
frozen contract it derives tenant + provider from the pinned `state` alone — never
from a client-supplied id — and then 302s back into the app.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse

from contracts.connections_http.schema import (
    AuthorizeResponse,
    ConnectionInfo,
    ConnectionsResponse,
)
from backend.tool_registry.catalog import CALENDAR_SCOPES, EMAIL_SCOPES, GMAIL, GOOGLE_CALENDAR
from backend.tool_registry.connections import ConnectionManager, ConnectionStore
from backend.tool_registry.errors import ProviderError, ToolError

# The connectable provider catalog, id -> the scopes `begin_connect` requests.
# Matches the least-privilege scopes the tool catalog already declares.
_PROVIDER_SCOPES: dict[str, list[str]] = {
    GOOGLE_CALENDAR: CALENDAR_SCOPES,
    GMAIL: EMAIL_SCOPES,
}


def current_tenant(x_tenant_id: Optional[str] = Header(default=None)) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return x_tenant_id


def _connections_response(store: ConnectionStore, tenant: str) -> ConnectionsResponse:
    """Every catalog provider, connected or not — so the UI can render a fixed list
    of connect buttons instead of only what happens to be connected already."""
    by_provider = {c.provider: c for c in store.list(tenant)}
    infos = [
        ConnectionInfo(
            provider=provider,
            connected=conn is not None,
            scopes=conn.scopes if conn else [],
            connection_ref=conn.connection_ref if conn else None,
        )
        for provider, conn in ((p, by_provider.get(p)) for p in _PROVIDER_SCOPES)
    ]
    return ConnectionsResponse(connections=infos)


def create_router(
    manager: ConnectionManager,
    store: ConnectionStore,
    *,
    redirect_uri: str,
    app_redirect_url: str = "/",
) -> APIRouter:
    """`redirect_uri` is the backend's OWN callback URL (must match what's registered
    with the provider); `app_redirect_url` is where the browser bounces back to in the
    app once the callback has run (frontend origin)."""
    router = APIRouter()

    @router.get("/connections")
    def list_connections(tenant: str = Depends(current_tenant)):
        return _connections_response(store, tenant).model_dump(mode="json")

    @router.post("/connections/{provider}/authorize")
    def authorize(provider: str, tenant: str = Depends(current_tenant)):
        scopes = _PROVIDER_SCOPES.get(provider)
        if scopes is None:
            raise ProviderError(f"Unknown provider: {provider}")
        url = manager.begin_connect(tenant, provider, scopes, redirect_uri)
        return AuthorizeResponse(authorization_url=url).model_dump(mode="json")

    @router.get("/oauth/callback")
    async def callback(code: str = Query(...), state: str = Query(...)):
        # Tenant + provider come from the state ConnectionManager pinned at
        # begin_connect — never trusted from this request (D-security).
        try:
            await manager.complete_connect(state, code)
        except ToolError:
            return RedirectResponse(url=f"{app_redirect_url}?connected=error")
        return RedirectResponse(url=f"{app_redirect_url}?connected=ok")

    @router.delete("/connections/{provider}")
    def disconnect(provider: str, tenant: str = Depends(current_tenant)):
        conn = store.for_provider(tenant, provider)
        if conn is not None:
            manager.disconnect(tenant, conn.connection_ref)
        return _connections_response(store, tenant).model_dump(mode="json")

    return router


def install_error_handler(app: FastAPI) -> None:
    @app.exception_handler(ToolError)
    async def _handle(_request, exc: ToolError):
        return JSONResponse(status_code=exc.http_status, content=exc.to_dict())


def create_app(
    manager: ConnectionManager,
    store: ConnectionStore,
    *,
    redirect_uri: str = "http://localhost:8000/api/oauth/callback",
    app_redirect_url: str = "/",
) -> FastAPI:
    """Standalone app factory (dev/tests). Production mounts `create_router` into the
    one app and injects the real session dep for `current_tenant`."""
    app = FastAPI(title="voice-agent-studio — connections")
    app.include_router(
        create_router(
            manager, store, redirect_uri=redirect_uri, app_redirect_url=app_redirect_url
        ),
        prefix="/api",
    )
    install_error_handler(app)
    return app
