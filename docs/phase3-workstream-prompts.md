# Dispatch kit — Phase 3 (7 workstreams, worktree-isolated)

Real integrations, dispatched in parallel. Full plan: `docs/phase3-plan.md`. Each worker runs
in its **own git worktree + branch**, so no two workers share a working copy or write the same
file. Freeze the three Phase-3 contracts (already done) and merge the foundation branch to the
dispatch base **before** dispatching.

## Why worktrees (and their limit)
A worktree is a separate working directory sharing the one repo. Two workers in two worktrees
never collide on files. The limit: they share **branches + committed history**, not uncommitted
work — so each worker commits only its own files, and NEVER runs `git add -A` (that can sweep in
another concern). Stage explicit paths.

## SHARED TEMPLATE
Give each worker this, with the per-stream insert appended.

> You are building ONE workstream of the voice-agent-studio Phase-3 real-integration effort.
> Read `CLAUDE.md`, `docs/decisions.md`, `docs/phase3-plan.md`, and your workstream README/
> contract before writing code. The relevant contracts are FROZEN — depend on them exactly; if
> one is insufficient, file `docs/contract-change-requests/<slug>.md` instead of editing it.
>
> **STEP 0 — ISOLATE (worktree + branch).** From the dispatch base (up-to-date `master` with the
> Phase-3 foundation merged), create your own worktree:
> `git worktree add ../vas-p3-<N>-<slug> -b p3/<N>-<slug>`
> Work only there.
>
> **STEP 1 — GRILL ME (scoped, tight).** Before code, run a short grilling session on THIS
> workstream's design decisions only (the ones in your insert). Resolve them, then build.
>
> **STEP 2 — BUILD WITHIN YOUR BOUNDARY.** Implement ONLY this workstream. Mock anything not yet
> merged behind its frozen contract. Do not edit files outside your path; do not mount routes in
> `integrated_app` (the integrator does that). Keep provider SDKs lazily imported inside your
> adapter.
>
> **STEP 3 — SELF-VERIFY (definition of done).** Meet the insert's DONE criteria. Add tests that
> run green WITHOUT network/keys (mock the provider); mark any live call as a documented smoke
> test. Run your package's tests + the repo's existing suite for files you touched.
>
> **STEP 4 — HAND OFF.** Commit on your branch (explicit paths only, never `git add -A`).
> Summarize what changed, which contract you rely on, any smoke test needing keys, and how to
> verify. Do NOT merge or remove your worktree — the integrator does both, in dependency order.

## PER-STREAM INSERTS

### P3-1 — Google Calendar client + OAuth + connect routes  (`backend/integration/google_calendar.py`, `backend/tool_registry/oauth.py`, connect routes)
Implement `GoogleCalendarClient` satisfying `contracts/provider_clients.CalendarClient` (real
Google Calendar `events.insert`). Wire `oauth.exchange_code` to Google's real token endpoint via
an injected async `httpx` poster. Implement the `contracts/connections_http` routes over the
existing `ConnectionManager` + `CredentialStore`. **Grill:** scopes (calendar.events), token
refresh, state/anti-forgery, redirect URI. **DONE:** unit tests with a stubbed HTTP poster
(no network) green; live smoke documented (real OAuth + one real booking); `providers.py`
`build_calendar_client()` returns it when `GOOGLE_OAUTH_CLIENT_ID` is set.

### P3-2 — Resend email client  (`backend/integration/resend_email.py`)
Implement `ResendEmailClient` satisfying `contracts/provider_clients.EmailClient` (Resend send
API; approved templates only, links unchanged). **Grill:** where the approved template store
lives, from/domain, error mapping to `ProviderError`. **DONE:** unit tests with a stubbed HTTP
client green; live smoke documented (`RESEND_API_KEY` → one real send); `providers.py`
`build_email_client()` returns it when the key is set.

### P3-3 — RetellTransport — real outbound phone  (`backend/voice_runtime/transports.py`)
Implement `RetellTransport.start/send_agent_utterance/receive/end` (+ optional `transfer`)
against the Retell SDK for a real outbound call, satisfying the FROZEN `CallTransport`. Lazily
import the SDK. **Grill:** how agent utterances/lead audio map to the SDK's streaming, the from-
number, call teardown. **DONE:** the transport factory already selects it when `RETELL_API_KEY`
is set; CI stays on `MockVoiceTransport`; live smoke documented (one real call, number masked in
events). Do NOT change the engine or the contract.

### P3-4 — Browser-voice backend WS bridge  (`backend/voice_preview/`)  *(new package)*
See `backend/voice_preview/README.md`. `BrowserVoiceTransport` (implements `CallTransport`)
bridging browser PCM ⇄ Gemini Live, driven by the existing `CallEngine`; a `create_router()`
exposing `WS /api/agents/{agent_id}/preview/voice` per `contracts/voice_preview`. **Grill:** the
audio↔text bridge (STT/TTS at the edge vs native Live) — must preserve code-emitted disclosure +
in-call tools + events. **DONE:** tests drive the transport with fake audio + a scripted wrapper,
asserting disclosure-first and the protocol frames; Gemini Live SDK lazily imported.

### P3-5 — Browser-voice frontend  (`frontend/src/preview/`)
See `frontend/src/preview/README.md`. Mic capture → 16 kHz mono PCM binary frames; playback of
agent audio; render transcript/disclosure/outcome/error/ended; Hang-up. **Grill:** resampling
(AudioWorklet), playback buffering, permission-denied UX. **DONE:** builds clean; talks to a mock
WS in a component test; matches `contracts/voice_preview` exactly.

### P3-6 — Connections + campaign-builder UI  (`frontend/src/`)
"Connect Google Calendar" flow against `contracts/connections_http`; a campaign builder that
creates a campaign, imports leads (phone + name, incl. CSV), and authorizes it against the
existing `/api/campaigns`. **Grill:** lead-import shape/validation, connection status display,
authorize confirmation (bounded autonomy is a deliberate click). **DONE:** builds clean; flows
work against a mock API in tests; no backend edits.

### P3-7 — Packaging  (root)
`requirements.txt` (fastapi, uvicorn, pydantic, httpx, google-genai, retell SDK, resend,
psycopg[binary], cryptography, anyio/pytest — reconcile the per-workstream requirements files);
`.env.example` documenting every key (`GEMINI_API_KEY`, `TOOL_REGISTRY_ENC_KEY`, `DATABASE_URL`,
`GOOGLE_OAUTH_CLIENT_ID/SECRET`, `RESEND_API_KEY`, `RETELL_API_KEY`, `RETELL_FROM_NUMBER`); a
run/setup doc (backend `uvicorn backend.integrated_app:app`, frontend dev proxy). **DONE:** a
clean checkout installs and boots in-memory with only `GEMINI_API_KEY`.

## INTEGRATION & E2E PROTOCOL (the integrator)
Merge in the `docs/phase3-plan.md` order (P3-7 → P3-1/2 → P3-3 → P3-4/5 → P3-6). After each merge
run the touched suites + `backend/integration`; mount any new routes in `integrated_app`; then
run the live smoke for that layer (keys required). After a branch is merged and green:
`git worktree remove ../vas-p3-<N>-<slug>` and delete the branch. Finish with the full E2E in the
plan. Contract insufficiency → a `docs/contract-change-requests/` entry, resolved before the
dependent merge.
