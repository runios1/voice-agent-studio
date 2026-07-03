# Phase-2 integration plan — make the merged modules run as one live stack

All seven Phase-2 workstreams are merged to master, but they were built **mostly-
mocked and in parallel**, and **nothing wires the Phase-2 backend into the running
app** (`backend/app.py` is still the Phase-1 assembly: agents/builder/preview only).
So there is no live full-stack E2E yet. This plan closes that gap with the **same D14
pattern** the project already uses: freeze one contract, then fan out into independent
workstreams that never touch each other's files.

**Frozen contract (the single source all instances bind to):**
`contracts/dashboard_http/README.md` — the dashboard ⇄ Phase-2 backend HTTP surface +
the backend assembly seam. Read it first. Do not edit it mid-flight; a change is
cross-cutting.

## The gap, concretely
The merged routers already expose the right routes (`orchestrator/control_api.py`,
`events/router.py`), and the orchestrator **emits `campaign.*` events through a
swappable sink** — so live, server-authoritative reflection works *if* one shared
`EventService` is threaded as that sink. What's missing is (1) the process that
assembles them, (2) the frontend HTTP client matching the real route shapes, and
(3) some live motion to watch. Those are the three streams below.

## Parallel decomposition (run in separate Claude instances / worktrees)

```
        FROZEN: contracts/dashboard_http/README.md
                        │
   ┌────────────────────┼─────────────────────┐
   ▼                    ▼                     ▼
 INT-A               INT-B                 INT-C (optional)
 backend assembly    frontend reconcile    demo scenario + live motion
 backend/phase2_app  frontend/src/dashboard backend/phase2_demo.py
   │                    │                     │
   └──────────► JOIN (sequential): run both, drive the browser E2E ◄──────┘
```

- **INT-A and INT-B are fully independent** — disjoint files (backend vs frontend),
  both bind only to the frozen contract. Either can finish first.
- **INT-C is independent too**: it implements the frozen `seed_and_run(orch, events)`
  signature against the in-memory module APIs, unit-tested with no HTTP. INT-A calls it
  if present and falls back to a minimal inline seed if not — so INT-C never blocks INT-A.
- **JOIN** is the one sequential step (you, or any one instance): bring up backend +
  frontend in real mode and drive the browser. Nothing else is sequential.

Each stream runs in its **own git worktree + branch** off up-to-date master
(`git worktree add ../vas-int-<x> -b int/<x>`), same as the Phase-2 fan-out. Workers
do NOT merge; the integrator merges A → B → C (order doesn't matter; they're disjoint)
then runs JOIN.

---

## SHARED TEMPLATE (paste into each instance, with the stream's insert)

```
You are the owner of Phase-2 INTEGRATION stream INT-<X> — <NAME> — for voice-agent-studio.

READ FIRST, then confirm you've internalized them:
  - CLAUDE.md, docs/decisions.md (D0–D14 + P2-D1–P2-D6 are SETTLED)
  - docs/phase2-integration-plan.md (this plan)
  - contracts/dashboard_http/README.md  (THE FROZEN CONTRACT — you bind to this, not to
    the other streams' code)
  - your target files: <TARGET>

THE CONTRACT IS FROZEN AND READ-ONLY. Bind to contracts/dashboard_http/README.md exactly.
If it is wrong/insufficient, STOP and write docs/contract-change-requests/int-<X>.md and
surface it — do NOT work around or silently edit it (that desyncs every instance).

STEP 0 — ISOLATE. From an up-to-date master:
    git worktree add ../vas-int-<X> -b int/<X>
  cd ../vas-int-<X> and do ALL work there, only within <TARGET> (+ your own tests).

STEP 1 — BUILD to the contract. Reach other streams ONLY through the frozen contract;
  MOCK/stub anything not yet merged. Match the repo's conventions and altitude. Keep the
  Phase-1 builder/preview app working.

STEP 2 — SELF-VERIFY (definition of done): <DONE>. Deliver automated tests that pass
  (show the run) and a short DONE.md (what's done, what's stubbed, exact verify commands).
  Report failures honestly.

STEP 3 — HAND OFF. Commit on your branch. Summarize what changed and which contract
  points you consumed. STOP — do not merge; the integrator merges and runs the JOIN E2E.
```

---

## PER-STREAM INSERTS

### INT-A — Backend Phase-2 assembly  (`backend/phase2_app.py` + its tests)
- **TARGET:** `backend/phase2_app.py` (new), `backend/tests/` for it. Do NOT edit the
  merged module internals or `backend/app.py`.
- **BUILD:** implement §4 of the contract — one `EventService`, the `EventServiceSink`
  adapter, an `OrchestratorService` (stub `ConfigSource` returning a default
  `AgentConfig`; mock `Dialer` from `backend/orchestrator/mocks.py`) wired with that
  sink; mount both routers under `/api`; override BOTH auth deps to `dev-user`; seed via
  `seed_and_run` if importable else a minimal inline seed; `GET /api/health`.
- **DONE:** `uvicorn backend.phase2_app:app` boots; `curl /api/campaigns` returns the
  seeded campaign(s); `POST /api/campaigns/{id}/pause` returns a paused Campaign AND a
  subsequent `GET /api/events?type=campaign.paused` shows the emitted event (proves the
  shared sink); `GET /api/events/stream` yields frames. Tests use FastAPI TestClient /
  httpx ASGITransport (note: ASGITransport buffers, so assert the stream via
  `event_sse_stream` directly, per events/router.py).

### INT-B — Frontend reconciliation  (`frontend/src/dashboard/`)
- **TARGET:** `frontend/src/dashboard/dashboardApi.ts` (+ `types.ts` if needed) and its
  tests.
- **ALREADY WIRED ON MASTER (do NOT redo, do NOT remove):** the dashboard is reachable
  from the builder UI — `App.tsx` header links to `/dashboard.html` ("Operations
  dashboard ↗") and `DashboardApp.tsx` links back ("← Agent studio"); `vite.config.ts`
  emits both HTML entries. The two surfaces stay separate roots/stores on purpose. You
  inherit this from master; just don't break it. The real-mode switch is simply
  `VITE_USE_MOCK=false` (dashboard `main.tsx` already reads it).
- **BUILD:** make `createHttpDashboardApi` match the frozen contract exactly (§1–§3):
  `/emergency-stop`; `getCampaign` = 2 fetches composed into `CampaignDetail`; `queryAudit`
  + `subscribeEvents` unwrap the `{seq,event}` row / `data.event`; repeated `type`/
  `severity` query params; escalate disabled in real mode (§3). Keep the mock API +
  `mockDashboardApi.ts` intact for tests/dev. Update `rawToEvent`/`filterToQuery`.
- **DONE:** `npx tsc -b --noEmit` clean; `npx vitest run src/dashboard` green (add/adjust
  tests for the new wire shapes — a small fixture proving `{seq,event}` unwrap and the
  2-call `CampaignDetail` compose); `npm run build` succeeds. Because the backend may not
  be up, verify against the contract's example shapes (static fixtures), not a live server.

### INT-C — Demo scenario + live producers  (`backend/phase2_demo.py` + its tests)  *(optional)*
- **TARGET:** `backend/phase2_demo.py` (new) + its tests. Nothing else.
- **BUILD:** implement the frozen `async def seed_and_run(orch, events, *, tenant, stop)`
  (contract §4c): authorize ≥1 campaign, then on a timer emit a realistic call-lifecycle
  sequence through `events.emit(...)` and trip at least one `orch.autopause(...)`, until
  `stop` is set. Share the passed-in instances (no new EventService). Keep payloads valid
  per `backend/events/payloads.py`.
- **DONE:** a unit test drives `seed_and_run` against in-memory `OrchestratorService` +
  `EventService` with a `stop` set after a few ticks, and asserts the expected event types
  landed in `events.query(...)` (incl. a `campaign.autopaused`). No HTTP.

---

## JOIN — the culminating browser E2E (sequential; integrator)
After merging A/B/[C]:
```bash
# backend
python -m uvicorn backend.phase2_app:app --host 127.0.0.1 --port 8000
# frontend (real mode)
cd frontend && VITE_USE_MOCK=false npm run dev
```
Open `http://localhost:5173/dashboard.html` and confirm the §5 checklist: seeded
campaigns on the fleet; live event trail; **Pause flips state via the stream** and the
event shows in Audit; Emergency-stop halts all; Audit filter/export works; escalate
disabled. A red check stops the line; reconcile against the frozen contract before
advancing.

## Not in this pass (explicitly deferred)
Real telephony (Retell/Gemini Live), per-tenant OAuth tool execution end-to-end, the
Postgres-backed stores, live escalate/warm-transfer, and auto-pause running as a live
stream consumer (INT-C simulates the trip directly). Those are the next integration
edges once this loop is green.
