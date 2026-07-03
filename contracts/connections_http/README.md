# contracts/connections_http — FROZEN (Phase 3)

The HTTP surface for connecting a tenant's tools (OAuth), so real calendar/email can act as
the tenant.

- **Implemented by:** **P3-1** (backend routes + OAuth token exchange), over the existing
  `ConnectionManager` + encrypted `CredentialStore`.
- **Called by:** **P3-6** (frontend "Connect Google Calendar" button + connection status).

Endpoints (see `schema.py` for payloads):

| Method | Path | Returns |
|---|---|---|
| GET | `/api/connections` | `ConnectionsResponse` |
| POST | `/api/connections/{provider}/authorize` | `AuthorizeResponse` (URL to redirect to) |
| GET | `/api/oauth/callback?code&state` | 302 back into the app |
| DELETE | `/api/connections/{provider}` | `ConnectionsResponse` |

**Security:** `state` is opaque, anti-forgery, and tenant-pinned; the callback derives tenant
+ provider from the stored `state`, **never** from client input. Client secrets come from env.
Tokens go straight to the tenant-scoped `CredentialStore` and never appear in a response.

Changing routes/payloads is a **contract-change-request**.
