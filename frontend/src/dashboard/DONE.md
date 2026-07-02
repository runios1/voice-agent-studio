# P2-7 — Dashboard frontend — DONE

The operations dashboard: four altitudes over the Phase-2 event stream (P2-D5) with
the kill-switch / emergency-stop controls (P2-D3). A **self-contained area** under
`frontend/src/dashboard/` — it does NOT touch the Phase-1 builder/preview app.
Depends only on the frozen `contracts/events` + `contracts/campaign` (mirrored
read-only in `types.ts`) and the P2-2 orchestrator control API (mocked; see below).

## Internal decisions (grill outcomes)
Proceeded on recommendations (kickoff was hands-off), stated back in chat:
- **Reuse vs separate:** reuse the frontend *project*, but the dashboard is a
  self-contained area with its own store, API seam, and dev entry
  (`dashboard.html` + `src/dashboard/main.tsx`). I did not touch `App.tsx`,
  `main.tsx`, or `vite.config.ts` — wiring the dashboard into the real app nav is the
  integrator's job (respects the "don't touch builder/preview surfaces" boundary).
- **Live transport:** SSE, reusing the repo's `src/api/sse.ts` `parseSseStream`
  (POST/fetch-stream pattern already established). `DashboardApi` mirrors `AgentApi`.
- **Server-authoritative, like the builder:** the UI never flips campaign state on a
  click. A pause/stop control calls the orchestrator; the resulting `campaign.*`
  event arrives on the stream and *that* reflects the new state (`applyLifecycle`).
  This is the P2-7 boundary — render stream truth, don't compute control state
  client-side. The mock demonstrates the full loop (control → event → UI).
- **Nav:** top tabs **Fleet | Audit**; Fleet drills Fleet → Campaign → Live-call via
  breadcrumb.
- **Audit:** filter (type/severity/campaign) passed to a **server-side** query
  (`queryAudit`, authoritative); **export** downloads the returned raw events as JSON
  (a faithful slice of the immutable compliance log — no client reshaping).

## What's done
- **Four views render off the event stream + campaign snapshots and update live:**
  - `FleetView` — every campaign, per-campaign live-call count (from the stream),
    per-campaign pause/resume, and the **global emergency stop**.
  - `CampaignView` — progress (lead-state tallies from the snapshot), live outcomes +
    guardrail-trip count (from the stream), live-calls list, event trail, auto-pause
    reason banner. Drills into a live call.
  - `LiveCallView` — call status derived from its trail, disclosure ✓ badge,
    transcript lines (when the stream carries `payload.utterance`), and the
    **escalate-to-human** control (P2-D6).
  - `AuditView` — filterable, exportable table over the immutable log.
- **Controls call the control API and reflect state:** pause / resume / emergency-stop
  / escalate all go through `DashboardApi`; state is reflected from the resulting
  stream events, with in-flight `pending` indicators and a calm error line on failure.
- **Live subscription lifecycle** — one SSE subscription, aborted on unmount; a
  `live/offline` indicator in the header.
- Pure derivations isolated in `metrics.ts` (activeCalls, callTrail, leadCounts,
  progress, outcomeCounts, guardrailTrips, applyLifecycle) so the views *render*
  rather than invent state.

## What's mocked (and where the real thing plugs in)
- **The whole backend**, behind the single `DashboardApi` seam (`dashboardApi.ts`):
  - `src/dashboard/mockDashboardApi.ts` — dev scaffolding for `npm run dev`: a few
    campaigns, an in-memory append-only log, and a scripted live scenario. Its control
    methods emit the reflecting `campaign.*` / `call.escalated` events back onto the
    stream, so the dev UI behaves like the real server-authoritative flow.
  - `src/dashboard/testMocks.ts` — fine-grained, push-driven doubles for tests.
  - **Integration flip:** run with `VITE_USE_MOCK=false` (FastAPI up) → the real
    `createHttpDashboardApi()` talks to the seam via the Vite `/api` proxy.
- **⚠ Orchestrator control API endpoints are ASSUMED, not frozen.** The event-stream
  reads (`GET /events`, `GET /events/stream`) bind to the frozen `contracts/events`.
  But the control + snapshot routes belong to **P2-2**, which has no frozen HTTP
  contract yet. `createHttpDashboardApi` assumes:
  - `GET  /campaigns`, `GET /campaigns/{id}`
  - `POST /campaigns/{id}/pause`, `POST /campaigns/{id}/resume`
  - `POST /control/emergency-stop`
  - `POST /calls/{id}/escalate`
  The **integrator must reconcile these with P2-2's real routes** (a one-file change in
  `dashboardApi.ts` — no component touches transport). No contract-change-request was
  filed: the frozen contracts (`events`, `campaign`) were sufficient, and the control
  routes are P2-2's to define, not a gap in a frozen contract.

## Contract points consumed
`contracts/events/schema.py` (Event / EventType / Severity — live subscription +
audit query) and `contracts/campaign/model.py` (Campaign / Lead / CampaignState /
LeadState — fleet + campaign snapshots), mirrored read-only in `src/dashboard/types.ts`.

## How to verify
```bash
cd frontend
npm install
npx tsc -b --noEmit            # clean
npx vitest run src/dashboard   # 34 dashboard tests, all green
npx vitest run                 # full suite 57 tests (23 Phase-1 + 34 here), green
npm run build                  # tsc -b && vite build — succeeds
npm run dev                    # http://localhost:5173/dashboard.html — live mock scenario
```
Automated coverage (all passing):
- `metrics.test.ts` — every pure derivation incl. lifecycle reflection + no double-dial count.
- `store.test.ts` — ingest + stream lifecycle reflection; control calls are
  server-authoritative (state flips from the reflecting event, not the click);
  control-failure surfaced; audit query; drill-down snapshot fetch.
- `dashboardApi.test.ts` — filter serialization + SSE-record → Event coercion.
- `FleetView.test.tsx` — render; live call-count update; pause → stream flips state;
  emergency-stop enable/disable + call; drill-down.
- `CampaignView.test.tsx` — progress from snapshot; live-call drill; auto-pause banner
  reflected from the stream.
- `LiveCallView.test.tsx` — status derivation; disclosure badge; transcript; escalate
  call + disable on call end.
- `AuditView.test.tsx` — rows from server query; filter re-queries; JSON export.

**Manual browser check (not run here — no browser extension connected in this
session):** `npm run dev`, open `/dashboard.html`, watch the fleet + a campaign's live
calls tick, drill into a live call, hit Pause/Emergency-stop and see state flip from
the stream, filter + export the audit log. The Vite dev server boots and serves the
page (verified); the RTL tests exercise these same flows against a real DOM.

## Handoff
Branch `p2/7-dashboard`, worktree `../vas-p2-7-dashboard`. Do NOT merge — the
integrator merges last (P2-5 → P2-3 → P2-2 → P2-1 → {P2-4,P2-6} → **P2-7**). At merge:
(1) reconcile the assumed control routes with P2-2; (2) mount `DashboardApp` into the
real app nav (or wire `dashboard.html` as a build input in `vite.config.ts`); (3) set
`VITE_USE_MOCK=false` and run the culminating full-loop E2E.
