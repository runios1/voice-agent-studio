# Phase 3 — Connect to everything (real tools, real voice, real tasks)

Phase 2 shipped every workstream green **against mocks**. Phase 3 makes it a real product:
real calendar + email, real outbound phone, a live **talking preview**, and a **spine** so a
user's authorized campaign actually runs the agent they built. The architecture was designed
for exactly this (D9 swap posture), so the real work slots **behind already-frozen seams** —
the critical path is tiny.

## Already in place — the integration backbone (`backend/integration/`)
Built and green (`backend/integration/tests/`): this is the "integration after everything is in
place" glue, and it already has the holes the parallel work plugs into.

- `config_source.py` — campaigns load the **built** `AgentConfig` (the studio's `AgentService`),
  not a stub. One config artifact, two loops.
- `supervisor.py` — `SupervisedOrchestrator`: authorizing a campaign **auto-runs** its dispatch
  loop (bounded autonomy); pausing drains, one loop per campaign (no double-dial).
- `dialer.py` — `RealDialer`: builds the per-agent tool registry from config and runs the real
  `CallEngine` over a pluggable transport.
- `runtime.py` — `ToolStack` (shared `ConnectionStore` + encrypted `CredentialStore` + provider
  clients) and the transport factory (**Retell when keyed, else scripted mock**).
- `providers.py` — env-gated mock↔real switch. **Lazily imports `google_calendar.py` /
  `resend_email.py` that don't exist yet — P3-1/P3-2 create them.**
- `persistence.py` — `DATABASE_URL`-toggled Postgres vs in-memory (config, events, campaigns).
- Plus: `voice_runtime/engine.py` now resolves the tenant connection via the registry
  (`resolve_context`), so real handlers receive `ctx.connection`; `app.py` exposes the studio
  singletons on `app.state` for composition.

## Frozen contracts (the whole critical path — freeze before dispatch)
Only three new agreements; everything else (`CallTransport`, tool_registry, campaign, events)
is already frozen.

1. `contracts/provider_clients` — `CalendarClient` / `EmailClient` Protocols (the exact surface
   the handlers call). Swap boundary for P3-1 + P3-2.
2. `contracts/voice_preview` — the browser⇄backend live-voice WS protocol. New seam for P3-4 + P3-5.
3. `contracts/connections_http` — the OAuth connect endpoints. Seam for P3-1 (backend) + P3-6 (UI).

## Workstreams (fan out — each its own git worktree + branch)

| # | Workstream | Path | Behind seam | Needs |
|---|---|---|---|---|
| **P3-1** | Google Calendar client + OAuth token exchange + connect routes | `backend/integration/google_calendar.py`, oauth wiring, connections routes | `provider_clients`, `connections_http`, Connection/Credential | contracts 1,3 |
| **P3-2** | Resend email client | `backend/integration/resend_email.py` | `provider_clients` (EmailClient) | contract 1 |
| **P3-3** | RetellTransport — real outbound phone | `backend/voice_runtime/transports.py` (RetellTransport) | `CallTransport` *(already frozen)* | none |
| **P3-4** | Browser-voice **backend**: WS bridge → Gemini Live | `backend/voice_preview/` | `voice_preview` + `CallEngine` | contract 2 |
| **P3-5** | Browser-voice **frontend**: mic capture + playback + Talk button | `frontend/src/preview/` | `voice_preview` | contract 2 |
| **P3-6** | Connections + campaign-builder UI | `frontend/src/` | `connections_http` + existing campaign API | contract 3 |
| **P3-7** | Packaging: `requirements.txt`, `.env.example`, run docs | root | — | none |

Backend-isolated: P3-1, P3-2, P3-3, P3-7. Frontend: P3-5, P3-6. P3-4 is backend but in its own
new package. No two streams write the same file.

## Integration order (the integrator, after each merge)
0. **P3-7 first** — so everything installs (`pip install -r requirements.txt`, frontend deps).
1. **P3-1 + P3-2** — `providers.py` already flips on env keys. Mount P3-1's connect routes in
   `integrated_app`. Live smoke (with keys): connect calendar, enable calendar/email on an
   agent, run a campaign → assert a real event + a real booking/email.
2. **P3-3** — transport factory already selects Retell when `RETELL_API_KEY` is set. Live smoke:
   one real outbound call (masked number in the event log).
3. **P3-4 + P3-5** — mount the preview WS route in `integrated_app`; click **Talk**, converse via
   Gemini Live; assert disclosure fires first + a tool books.
4. **P3-6** — connect-calendar + campaign-builder UI against the live backend.
5. **Full E2E** — build agent → connect calendar → talk to it (preview) → create campaign with
   real leads → authorize → real call → real booking → dashboard event trail.

## Guardrails carried into Phase 3
Never commit secrets (client secrets/API keys from env only, never a model's context). Tenant
isolation stays server-side in code. A field's presence implies the runtime can honor it. Real
provider SDKs stay lazily imported inside their adapter (D8). Locks/guardrails enforced server-
side; the UI only reflects them.
