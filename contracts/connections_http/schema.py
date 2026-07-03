"""FROZEN CONTRACT — the HTTP surface for connecting a tenant's tools (Phase 3).

To book on a real calendar the tenant must first grant access (OAuth). These are the
endpoints the frontend "Connect Google Calendar" flow (**P3-6**) calls and the backend
(**P3-1**) implements. It is a thin HTTP skin over the EXISTING `ConnectionManager`
(`backend/tool_registry/connections.py`: `begin_connect` / `complete_connect` / `disconnect`)
and the encrypted, tenant-scoped `CredentialStore` — so the security model is unchanged; this
only names the routes + payloads both sides agree on.

Routes (all under /api, dev auth = fixed dev user, tenant scoped in code):

    GET    /api/connections
        -> ConnectionsResponse   # which providers this tenant has connected

    POST   /api/connections/{provider}/authorize
        -> AuthorizeResponse     # begin OAuth; returns the URL to send the browser to.
                                 # Server stores an opaque, tenant-pinned `state`.

    GET    /api/oauth/callback?code=...&state=...
        -> 302 redirect back into the app (the browser lands here from the provider).
        # Server exchanges code->tokens, writes them to the credential store, and creates
        # the Connection. `state` is validated (anti-forgery + tenant pin). Never trust a
        # client-supplied tenant/provider here — both come from the stored `state`.

    DELETE /api/connections/{provider}
        -> ConnectionsResponse   # revoke: delete the credential + connection for this tenant.

`provider` is one of the catalog provider ids: "google_calendar", "gmail" (see
`backend/tool_registry/catalog.py`). Client secrets come from the environment, never the repo,
never a model's context.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ConnectionInfo(BaseModel):
    provider: str                      # "google_calendar" | "gmail" | ...
    connected: bool
    scopes: list[str] = []
    # Opaque handle; never the token itself. Present only when connected.
    connection_ref: Optional[str] = None


class ConnectionsResponse(BaseModel):
    connections: list[ConnectionInfo]


class AuthorizeResponse(BaseModel):
    # Where the frontend redirects the browser to grant access.
    authorization_url: str
