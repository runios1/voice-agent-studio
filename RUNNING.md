# Running the integrated stack (Phase 1)

All six workstreams are wired into one FastAPI app by `backend/app.py` (the
integration assembly). The frontend talks to it through the Vite `/api` proxy.

> **Full stack (Phase 1 + Phase 2) in one backend:** run `backend/integrated_app.py`
> instead of `backend/app.py`. It composes the studio assembly (`/api/agents`, builder,
> preview) with the ops-dashboard assembly (`/api/campaigns`, `/api/events`) so BOTH
> frontend surfaces work against one `:8000`. Running only one of the two apps 404s the
> other surface.
> ```bash
> set -a && source .env && set +a
> python -m uvicorn backend.integrated_app:app --host 127.0.0.1 --port 8000
> # frontend (real mode, serves both / and /dashboard.html):
> cd frontend && VITE_USE_MOCK=false npm run dev
> ```

## Real accounts + persistence (`backend.integrated_app`)
Open http://localhost:5173 and you land on a **sign-in screen** ("Sign in with
Google"), not a pre-loaded demo agent — there is no fixed dev user anymore.
Whoever signs in is a real, durable identity, and their agents/campaigns/events
are scoped to them (`backend/auth`).

- **Storage is durable by default**, zero config: with `DATABASE_URL` unset, every
  store (agents, campaigns, events, accounts) persists to a SQLite file at
  `./.data/vas.db` (gitignored) — restart the backend and everything is still
  there. Set `DATABASE_URL` to a libpq DSN to use Postgres instead (same
  Protocols, no code change); set `VAS_IN_MEMORY=true` for a fully ephemeral
  boot (tests/CI only).
- **Google sign-in reuses the Calendar/Gmail OAuth client** (`GOOGLE_OAUTH_CLIENT_ID`/
  `_SECRET` in `.env`) but a different callback path, so it needs an **additional
  redirect URI registered** on that same client (Google Cloud Console → APIs &
  Services → Credentials → your OAuth client → Authorized redirect URIs):
  ```
  http://localhost:8000/api/auth/google/callback
  ```
  Without `GOOGLE_OAUTH_CLIENT_ID` set at all, sign-in still works end-to-end
  against a no-network fake identity (`FakeGoogleLoginProvider`) — fine for a
  quick local run, not for anything beyond localhost.
- A brand-new user gets one agent auto-created on first sign-in (mirrors the old
  `agent-demo` convenience); returning users land back on their most recently
  updated agent.

## Setup from a clean checkout
```bash
pip install -r requirements.txt
cp .env.example .env    # then fill in GEMINI_API_KEY
cd frontend && npm install && cd ..
```
`.env.example` documents every key the backend reads. Only `GEMINI_API_KEY` (or
`GOOGLE_API_KEY`) is required to boot — everything else (Postgres persistence,
Model Armor screening, Google Calendar, Resend, Retell) gates one optional real
integration and falls back to an in-memory/mock implementation when unset, so
this same checkout boots and runs a full campaign end-to-end with just the one key.

## Prerequisites
- A Gemini API key in `.env` at the repo root (gitignored):
  ```
  GEMINI_API_KEY=...
  ```
  Nothing auto-loads it — source it into the shell before launching the backend.
- Python deps: `pip install -r requirements.txt` (one root file for the whole repo).
- Frontend deps: `cd frontend && npm install`.

## Start the backend (:8000)
```bash
set -a && source .env && set +a
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```
Health check: `curl localhost:8000/api/health` → `{"ok":true,"demo_agent":"agent-demo"}`.

## Start the frontend (:5173, talks to the real backend)
```bash
cd frontend
VITE_USE_MOCK=false npm run dev
```
Open http://localhost:5173. The Vite dev server proxies `/api` → `:8000`.
(Omit `VITE_USE_MOCK=false` to run the UI against its in-repo mock, no backend.)

## What the assembly wires (`backend/app.py`)
```
GeminiWrapper (WS6)  ──►  ScreeningModelWrapper (WS5)  ──►  BuilderLoop (WS3)
                                                         └►  RuntimeEngine (WS4)
AgentService + InMemoryConfigRepository (WS2)  ──►  /agents, PATCH /fields,
                                                    builder gate, preview provider
```
Routes (all under `/api`):
- `POST/GET /api/agents`, `GET /api/agents/{id}`, `PATCH /api/agents/{id}/fields` — WS2
- `POST /api/agents/{id}/builder/messages` (SSE) — builder loop, assembled here
- `POST /api/agents/{id}/preview/messages` (SSE) — WS4

## Phase-1 shortcuts (`backend.app` standalone only — dev/test, not the full stack)
Running `backend.app:app` directly (rather than `backend.integrated_app:app`) has
no auth routes and no Phase-2 surfaces, so it keeps the original dev shortcuts:
- **Auth** is a fixed dev user (`current_user` dependency overridden); pass
  `user_dependency=...` to `build_app()` to plug in a real one (that's exactly
  what `integrated_app.py` does with `backend.auth`).
- **Storage** is still durable SQLite by default, but a demo agent (`agent-demo`)
  is seeded for the fixed dev user so the frontend's default `VITE_AGENT_ID`
  resolves without a create step (idempotent — seeded once, not on every restart).
- **Screening of the trusted system prompt is skipped** at the model-call boundary
  (`IntegrationScreeningWrapper`): the builder's system prompt *describes* the locked
  guardrails, which the WS5 guardrail-domain heuristic would otherwise read as a
  subversion attempt. User free-text is still screened at the config gate on write,
  and AI disclosure is code-emitted at runtime regardless.

## Verified end-to-end (real Gemini)
- `GET /agents/agent-demo` → config + resolved field policy.
- `PATCH .../fields` open field accepted (version bumps); locked path → `403` with
  `{"error":{"kind":"locked_path",...}}`.
- Builder SSE streams `patch` events that mutate the shared config.
- Preview SSE emits the code-emitted AI-disclosure line first, then the model reply.
