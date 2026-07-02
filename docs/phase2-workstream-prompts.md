# Dispatch kit — Phase 2 (7 workstreams, worktree-isolated)

Same shape as `docs/workstream-prompts.md` (Phase 1), for the Phase-2 plan
(`docs/phase2-plan.md`). Each worker runs in its **own git worktree + branch**, so
no two workers ever touch the same working copy.

How to use:
1. **Freeze the 4 Phase-2 contracts first** (event schema, tool registry, campaign/
   lead model, voice-runtime interface). Do NOT dispatch until frozen — un-frozen
   contracts + parallel workers = merge hell (D14).
2. For each workstream, paste **the shared template** with that stream's **insert**
   into a fresh Claude Code session opened in the repo.
3. Kickoff **grills are sequential** — you answer each. One at a time, or tell the
   agent to proceed on its recommendations.
4. **Integrate in dependency order** (bottom): P2-5 → P2-3 → P2-2 → P2-1 →
   {P2-4, P2-6} → P2-7. Workers do NOT merge; the integrator merges and removes the
   worktree.

### Why worktrees (and their limit)
A worktree is a separate working directory sharing the one repo. It guarantees
**physical isolation while working**. It does NOT prevent a *merge conflict* if two
streams edit the same file — that's prevented by BOUNDARIES: each stream owns
distinct dirs, `contracts/` is read-only, and shared app assembly is the
integrator's job. Worktrees + boundaries = the "never two writers in one file" goal.

---

## SHARED TEMPLATE

```
You are the owner of Phase-2 Workstream P2-<N> — <NAME> — for voice-agent-studio.

READ FIRST (in this order), then confirm you've internalized them:
  - README.md, CLAUDE.md, docs/decisions.md (D0–D14 + P2-D1–P2-D6 are SETTLED)
  - docs/phase2-plan.md  (the Phase-2 architecture + your row)
  - contracts/  (READ-ONLY — see rule below)
  - your workstream target dir: <WS_DIR>

CONTRACTS ARE FROZEN AND READ-ONLY. Do not edit anything under contracts/. If a
contract is wrong/insufficient, STOP: write docs/contract-change-requests/p2-ws<N>.md
and surface it. Do NOT work around, fork, or silently edit it — that breaks every
other stream.

STEP 0 — ISOLATE (worktree + branch). From the main repo root, on an up-to-date
main, create your own worktree so no other worker shares your files:
    git worktree add ../vas-p2-<N>-<slug> -b p2/<N>-<slug>
Then cd ../vas-p2-<N>-<slug> and do ALL your work there. Stay inside <WS_DIR>
(plus your own tests). Do not edit other workstreams' directories or shared app
wiring — that's the integrator's job.

STEP 1 — GRILL ME (scoped, tight). Before code, run a grilling session on THIS
workstream's INTERNAL decisions only — libraries, structure, edge cases in your
boundary. Do NOT reopen the settled D-/P2-D- decisions. One question at a time,
each with your recommended answer. Suggested topics: <GRILL_TOPICS>. If I say "you
decide," take your recommendation and move on.

STEP 2 — BUILD WITHIN YOUR BOUNDARY. Implement ONLY this workstream. Reach other
streams ONLY through frozen contracts; MOCK anything not yet merged (a fake voice
platform, a fixture event stream, a stub tool registry). Emit to the event stream
per its schema. Match the repo's conventions and altitude.

STEP 3 — SELF-VERIFY (definition of done): <DONE_CRITERIA>. Deliver:
  - automated tests that pass (show the run),
  - where a runnable surface exists, prove behavior with the /verify skill,
  - a DONE.md in <WS_DIR>: what's done, what's mocked, exact verify commands.
    Report failures honestly.

STEP 4 — HAND OFF. Commit on your branch. Summarize what changed, which contract
points you consumed, and what you mocked. STOP — do not merge to main and do not
remove your worktree; the integrator does both in dependency order after E2E.
```

---

## PER-STREAM INSERTS

### P2-1 — Voice runtime  (`backend/voice_runtime/`)
- **GRILL:** how the Phase-1 text runtime loop generalizes into a shared call-session
  abstraction; managed-platform (Retell) SDK integration; in-call function latency
  budget; mapping the platform's tool-calling to our tool registry; warm-transfer
  mechanics; recording/consent capture.
- **DONE:** a call session starts/monitors/ends through the voice-runtime interface
  (voice platform mocked in CI); in-call fast functions execute against the registry;
  the AI-disclosure step fires; warm-transfer path works; live smoke test documented.

### P2-2 — Campaign orchestrator  (`backend/orchestrator/`)
- **GRILL:** queue tech (RQ/Celery+Redis vs cloud); per-lead state machine + Postgres
  schema; idempotency / no-double-dial; concurrency + rate-limit + calling-hours;
  the kill-switch flag mechanism and how workers check it; crash-resume-from-DB.
- **DONE:** authorize a campaign → workers dial leads (mock voice runtime) honoring
  rate/hours; per-lead state persists and RESUMES after a simulated crash with no
  double-dial; campaign pause + global stop + an auto-pause hook each halt new dials
  and let in-flight finish; tests cover resume + all three stops.

### P2-3 — Tool registry + integrations  (`backend/tool_registry/`)
- **GRILL:** registry-entry schema (scopes, param JSON Schema, in-call vs post-call,
  guardrails); per-tenant OAuth flow + encrypted token storage; how config.automation
  references entries; the least-privilege param enforcement point; wishlist→registry
  graduation.
- **DONE:** catalog with ≥ calendar + email entries; per-tenant OAuth connect +
  encrypted, tenant-scoped execution; guardrailed params rejected (non-allowlisted
  link domain, out-of-hours slot); a cross-tenant access attempt is DENIED; tests.

### P2-4 — Async workflows  (`backend/async_workflows/`)
- **GRILL:** embed n8n vs a small self-built runner; event-driven vs outcome-hook
  triggers; email template system; retry/backoff for no-answers; idempotency.
- **DONE:** a call-outcome event fires the right post-call workflow (confirmation
  email via registry, CRM write, scheduled follow-up); follow-up delays honored;
  idempotent on replay; tests with fixture outcome events.

### P2-5 — Event stream + observability backbone  (`backend/events/`)  *(foundational)*
- **GRILL:** bus tech (Postgres LISTEN/NOTIFY vs Redis streams vs Kafka — pick the
  simplest that supports live subscribe + a durable log); event envelope schema;
  immutable audit storage + retention; live transport to the dashboard (SSE/WS);
  analytics aggregation.
- **DONE:** components emit typed events; events persist to an IMMUTABLE log; a
  subscriber gets them live; audit query/filter/export works; basic analytics
  aggregation; tests for envelope, ordering, and append-only immutability.

### P2-6 — Auto-pause / escalation engine  (`backend/autopause/`)
- **GRILL:** detection approach (windowed counters/thresholds vs rules) over the
  stream; which patterns trip (guardrail-trip count, anomaly heuristics); escalation
  routing; debounce/cooldown to avoid flapping; how it invokes the orchestrator
  kill-switch.
- **DONE:** consuming the event stream, N guardrail-trips in a window trips the
  campaign kill-switch and emits `campaign.autopaused`; escalation fires on defined
  conditions; no flapping under cooldown; tests with synthetic event sequences.

### P2-7 — Dashboard frontend  (`frontend/` dashboard area)
- **GRILL:** reuse the Phase-1 React app vs a separate area; live transport (SSE/WS
  subscription); the four view altitudes + navigation; how kill-switch / global
  emergency-stop controls call the orchestrator control API; audit filter/export UX.
- **DONE:** fleet / campaign / live-call / audit views render from the event stream
  and update live; kill-switch + global emergency-stop call the control API and
  reflect state; audit filter + export; tests for rendering + live update.

---

## INTEGRATION & E2E PROTOCOL  (the integrator)

Merge in dependency order; run the E2E checks whose deps just closed; then
`git worktree remove ../vas-p2-<N>-<slug>` and delete the merged branch.

| Merge step | Bring in | E2E now runnable |
|---|---|---|
| 1 | **P2-5** event stream | Components emit; a subscriber receives; the audit log is append-only. |
| 2 | **P2-3** tool registry | Connect a tenant calendar (OAuth); a guardrailed param is rejected; cross-tenant denied. |
| 3 | **P2-2** orchestrator | Authorize a campaign; workers dial (mock voice) honoring hours/rate; pause halts new dials; crash-resume, no double-dial. |
| 4 | **P2-1** voice runtime | A real call session runs; in-call function books via the connected calendar; disclosure fires; events emitted. |
| 5 | **P2-4** async + **P2-6** auto-pause | Post-call confirmation/follow-up fires on outcome; N guardrail-trips auto-pause the campaign. |
| 6 | **P2-7** dashboard | Full loop: authorize a campaign, watch a live call + event trail on the dashboard, hit pause, see it stop. |

**Culminating E2E:** one authorized campaign dials one test lead through the real
voice runtime, books via a connected calendar, emits the full event trail, honors a
mid-campaign pause, and shows correctly on the dashboard.

At each step confirm the merge replaced any mock with the real path before advancing.
A red check stops the line.
```
