# contracts/provider_clients — FROZEN (Phase 3)

The swap boundary between the tool handlers and the real calendar/email providers.

- **Consumed by:** `backend/tool_registry/handlers.py` (the only caller).
- **Implemented by:** the mocks (`backend/tool_registry/integrations.py`, already satisfy it)
  and the real clients — **P3-1** (`GoogleCalendarClient`) and **P3-2** (`ResendEmailClient`).
- **Selected by:** `backend/integration/providers.py` (env-gated; already wired).

`CalendarClient` / `EmailClient` are structural `Protocol`s matching the exact method surface
the handler already uses (`book`, `get_template`, `send`) and the exact result attributes it
reads. A real client satisfies the contract by exposing the same shape — no inheritance.

**Invariants a client must rely on (not re-check):** the handler resolves the tenant's own
token in code and enforces every guardrail *before* calling the client. A client performs the
action and, on any provider failure, raises `ProviderError` (never a raw SDK exception — the
SDK must not leak past the adapter).

Changing this surface is a **contract-change-request** (`docs/contract-change-requests/`), not
an edit — the handler and both real clients depend on it.
