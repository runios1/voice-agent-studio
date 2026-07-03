# P3-7 — Packaging — DONE

Root-level packaging so a clean checkout installs and boots the whole stack behind
one file each: `requirements.txt` (Python), `.env.example` (every env key), and
`RUNNING.md` (run/setup doc, extended for Phase 3). `docs/phase3-plan.md` dispatches
this stream first so everything else installs cleanly once merged.

## What's done
- **`requirements.txt`** (root) — reconciles the three scattered per-workstream
  files (`backend/config_gate/requirements.txt`, `backend/security/requirements-dev.txt`,
  `backend/autopause/requirements.txt`, all now just point back here) plus the deps
  those files never listed: `google-genai` (WS6), `cryptography` (Fernet credential
  encryption), `anyio` (the anyio-marked async tests). Optional/lazy real-provider
  deps (`psycopg[binary]`, `retell-sdk`, `resend`) are listed but commented out,
  same convention `config_gate`'s file already used for `psycopg` — installed only
  when the operator actually wants that real integration. Google Calendar and Model
  Armor need no dedicated SDK; both go over `httpx`, already required.
- **`.env.example`** (root) — every env var actually read via `os.getenv`/`os.environ`
  across `backend/` and `contracts/` (grepped, not guessed): the required
  `GEMINI_API_KEY`/`GOOGLE_API_KEY`, Vertex swap vars, per-tier model overrides,
  Model Armor screening vars, `DATABASE_URL`, `TOOL_REGISTRY_ENC_KEY`, and the
  three Phase-3 provider pairs (`GOOGLE_OAUTH_CLIENT_ID/SECRET`, `RESEND_API_KEY`,
  `RETELL_API_KEY`/`RETELL_FROM_NUMBER`). Each optional block says which mock it
  falls back to when unset, traced against `backend/integration/providers.py` and
  `backend/integration/runtime.py`.
- **`RUNNING.md`** — added a "Setup from a clean checkout" section
  (`pip install -r requirements.txt`, `cp .env.example .env`, `npm install`) ahead
  of the existing backend/frontend run instructions, which were left unchanged.

## Verified
- Traced every `os.getenv`/`os.environ` call site in `backend/` and `contracts/`
  to confirm `.env.example` has no missing or stale keys.
- Confirmed each optional key's fallback path in code (not assumed): `providers.py`
  (`calendar_is_real`/`email_is_real`), `runtime.py` (`build_tool_stack` ephemeral
  Fernet key + warning, `make_transport_factory` mock fallback), `persistence.py`
  (`using_postgres`), `security/config.py` (`ScreeningConfig.from_env`, fail-open
  when Model Armor is unset).
- `pip install -r requirements.txt` into a fresh venv, then
  `python -m uvicorn backend.integrated_app:app` with only `GEMINI_API_KEY` set —
  boots clean, `GET /api/health` → `{"ok":true,...}` (see verification note below).
- `pytest` on each package this stream touched (`backend/config_gate`,
  `backend/security`, `backend/autopause`, `backend/integration`) still green
  after the requirements-file edits — confirms the packages didn't lose a pin
  the tests actually import. (A full `pytest backend contracts` run hits a
  pre-existing test-module-basename collision — `test_engine.py`/`test_tools.py`/
  `test_scheduling.py` duplicated across packages without `__init__.py` — that
  reproduces identically on unmodified `master`; not introduced by this stream
  and out of its boundary to fix.)

## Boundary
`requirements.txt`, `.env.example`, `RUNNING.md`, the three per-workstream
requirements files (content only, not deleted — other streams may still run their
suite in isolation from them), and this file. No code changes; no contract changes;
`integrated_app.py` untouched (mounting new routes for P3-1..P3-6 is the
integrator's job per the dispatch kit, not this stream's).
