# voice-agent-studio

**Chat with a builder AI to generate a voice-AI SDR agent** — one that phones
leads, qualifies them in a natural back-and-forth, books a meeting on a real
calendar, and emails the confirmation. You describe the agent in plain language;
the platform turns that conversation into a structured, guardrailed configuration
and runs it.

> 🔗 **Live demo:** https://voice-agent-studio-3rub.onrender.com/
> 📄 **Full product spec & architecture:** [`CLAUDE.md`](./CLAUDE.md)
> 🔒 **Locked design decisions:** [`docs/decisions.md`](./docs/decisions.md)

The core idea is a **two-layer control split**: the *provider* sets locked
guardrails and sensible defaults (AI disclosure, Do-Not-Call, calling hours, no
out-of-range promises); the *end user* tunes the details within those rails. That
split is only valuable because this is a **vertical** product — outbound sales /
lead qualification — where those guardrails are genuinely specific and worth
enforcing.

---

## What works today

This is a running end-to-end system, not a scaffold:

- **Builder chat → live config.** A goal-seeking interviewer (Gemini) edits a
  structured config as you talk. It emits **schema-constrained tool-call patches**
  (never a regenerated prompt blob), each routed through a server-side config gate.
  An Agent panel shows the agent's identity materializing field-by-field as answers
  decide it.
- **Real voice agent.** Gemini Live is the agent itself — audio-to-audio, natural,
  native tool-calling. Talk to it in the browser (mic ⇄ Live) or have it place a
  **real outbound phone call over Twilio** (Media Streams, G.711 μ-law bridge).
- **Real automation.** The agent checks live **Google Calendar** availability, books
  a slot, and sends the confirmation by **email (Resend)** — behind a swappable
  provider seam, with a mock fallback when a provider isn't configured.
- **Real accounts + durable storage.** Google sign-in; per-user isolation; agents,
  campaigns, and events persist to Postgres (or zero-config local SQLite).
- **Ops dashboard** over a structured event stream, plus bounded-autonomy campaign
  controls and an auto-pause kill switch.
- **One-file deploy.** A single Docker web service serves the API, the live
  WebSockets, and the built React app on one origin (Render blueprint included).

## The interesting engineering

- **Config is the single source of truth.** One schema
  (`contracts/config_schema/`) simultaneously (a) constrains generation, (b) drives
  validation, (c) renders the UI, and (d) is executed at runtime. An agent is a
  *structured config object with free-text pockets* — never a prompt blob.
- **Security by removing capability, then screening.** Enforcement lives at a
  source-agnostic config gate: every mutation (builder patch, manual edit, or forged
  request) passes the *same* checks. Critical guardrails (AI disclosure, DNC) are
  hard runtime steps **in code**, not prompt text a persona could override. Tenant
  data is scoped in code; secrets never enter a model's context; connected-tool
  tokens are Fernet-encrypted at rest. An off-the-shelf screener is the *outer,
  allowed-to-fail* layer — never the one relied on.
- **Reliability: constrain → validate → recover.** Provider-native constrained
  tool-calling makes malformed output structurally hard; each patch is validated
  against the schema; a semantic slip triggers a bounded retry, and the user sees a
  calm reprompt — never a stack trace.
- **Built for parallelism.** A tiny critical path (three frozen contracts), then a
  wide fan-out of independent workstreams, each in its own git worktree against those
  frozen seams. Real integrations (calendar, email, phone, live voice) slot in
  behind pre-frozen interfaces without a rewrite.

## Tech stack

React (Vite) · Python / FastAPI · Postgres (`jsonb`) or SQLite · SSE + WebSockets ·
Gemini (builder brain + Gemini Live voice) behind a provider-agnostic model wrapper ·
Twilio (telephony) · Google Calendar + Resend (automation) · Docker / Render.

## Run it locally

Full setup and run instructions are in **[`RUNNING.md`](./RUNNING.md)**. The short
version:

```bash
pip install -r requirements.txt
cp .env.example .env          # then fill in GEMINI_API_KEY
cd frontend && npm install && cd ..

# backend (:8000) + frontend (:5173)
set -a && source .env && set +a
python -m uvicorn backend.integrated_app:app --port 8000
cd frontend && VITE_USE_MOCK=false npm run dev
```

Only `GEMINI_API_KEY` is required to boot — every other integration (Postgres,
Google Calendar, Resend, Twilio, model screening) gates one optional real provider
and falls back to an in-memory/mock implementation when unset, so a clean checkout
runs a full campaign end-to-end on that one key. `.env.example` documents every key.

## Repo map

| Path | What's there |
|---|---|
| `contracts/` | Frozen seams: config schema, API, model wrapper, tool registry |
| `backend/builder_loop/` | The goal-seeking interviewer (chat that *edits* the config) |
| `backend/live_agent/` · `voice_preview/` · `voice_runtime/` | Gemini Live voice agent + browser/phone bridges |
| `backend/config_gate/` | The server-side enforcement boundary + persistence |
| `backend/integration/` | Real providers, orchestrator, dialer behind frozen switches |
| `backend/security/` | Model-armor screening at the wrapper |
| `frontend/` | Chat-first UI, Agent panel, live preview, ops dashboard |
| `docs/` | Decision log + per-phase plans and dispatch kits |

## How it was built

Developed with heavy AI assistance (Claude), coordinated across parallel
workstreams against frozen contracts — the git history reflects that, by design.
The phase-by-phase plans and dispatch kits live in [`docs/`](./docs/).
