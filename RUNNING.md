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

## Phase-1 shortcuts (dev only)
- **Auth** is a fixed dev user (`current_user` dependency overridden); real session
  auth drops in without route changes (tenant scoping is already enforced in WS2 code).
- **Storage** is in-memory with a seeded demo agent (`agent-demo`) so the frontend's
  default `VITE_AGENT_ID` resolves without a create step.
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
