# P3-6 — Connections UI

**Consumes:** `contracts/connections_http` (FROZEN, Phase 3) — implemented server-side
by P3-1 over the existing `ConnectionManager` + encrypted `CredentialStore`.

## Responsibility
- Render the tenant's tool-connection status (Google Calendar, Gmail) against the
  provider catalog and let them Connect (redirect into OAuth) or Disconnect
  (revoke, behind a deliberate second-click confirm).
- Own no OAuth logic and no token handling — this client only ever sees an opaque
  `connection_ref`, never a token (contract README §Security). The actual
  authorization URL and code exchange are entirely server-side.

## Boundaries — do NOT
- Do not store or log tokens/secrets; the server never sends them.
- Do not invent routes/payloads beyond `contracts/connections_http/schema.py` — if
  the seam is insufficient, file `docs/contract-change-requests/`.
- `navigate()` is injected (defaults to a real `window.location` redirect) so tests
  never trigger a real browser navigation.
