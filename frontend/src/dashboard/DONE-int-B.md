# INT-B — Frontend reconciliation — DONE

Reconciled the dashboard's HTTP client with the **frozen** dashboard ⇄ backend seam
(`contracts/dashboard_http/README.md`). The dashboard now calls exactly the routes the
already-merged orchestrator control API + event backbone serve, and consumes their real
wire shapes. Mock/dev + all tests stay green.

## What changed (all in `frontend/src/dashboard/`, + one shared UI primitive)

- **`dashboardApi.ts`** — `createHttpDashboardApi` now matches the contract:
  - `getCampaign(id)` = **two** reads (`GET /campaigns/{id}` + `GET /campaigns/{id}/leads`)
    composed into `CampaignDetail` (§1). Was a single `GET /campaigns/{id}`.
  - `queryAudit(filter)` = `GET /api/events?…` then **unwraps each `{seq,event}` row to
    `row.event`** → `Event[]` (§2).
  - `rawToEvent` reads the Event from **`data.event`** (the wrapped row); still tolerates a
    bare `Event` for the mock/legacy path (§2).
  - `filterToQuery` emits **repeated `type=`/`severity=`** params (not comma-joined
    `types=`) (§2).
  - `emergencyStopAll` → **`POST /api/emergency-stop`** (tenant-global), was
    `/control/emergency-stop` (§1).
  - `escalateCall` is **deferred (§3)**: no route exists, so it rejects with a
    `ControlFailure` **without issuing a fetch**, and the api exposes
    `escalateAvailable = false`.
- **`types.ts`** — added the `EventRow = { seq, event }` wire shape.
- **`store.ts`** — added `escalateAvailable` state, set from `api.escalateAvailable` at
  `init` (defaults `true`; mock/dev keep escalate enabled).
- **`LiveCallView.tsx`** — the Escalate control is disabled with a
  `title="Not available in this build"` when `escalateAvailable` is false (§3).
- **`ui.tsx`** — `ControlButton` gained an optional `title` prop (for the §3 tooltip).
- **`testMocks.ts`** — `resetStore` now clears `escalateAvailable` back to `true`.

## Preserved (inherited from master; NOT touched)
- Discoverability: `App.tsx` ↔ `DashboardApp.tsx` cross-links and both Vite HTML entries
  (`index.html` + `dashboard.html`) — confirmed still emitted by `npm run build`.
- The mock API (`mockDashboardApi.ts`) + `testMocks.ts` doubles remain intact for dev/tests.
- Real-mode switch is unchanged: `VITE_USE_MOCK=false` (dashboard `main.tsx`).
- Server-authoritative reflection: campaign state still flips from the stream event
  (`applyLifecycle`), never on the click.

## Stubbed / not verified here
- **No live backend.** Wire shapes are verified against the contract's example shapes via
  static fixtures (stubbed `fetch`), not a running server — per the INT-B DONE note. The
  live browser E2E is the integrator's JOIN step after INT-A merges.
- **Export** kept as the existing client-side JSON export of loaded rows (§2 allows this or
  linking `GET /events/export`; chose the former, unchanged).
- `after_seq` reconnect tracking not implemented (contract marks it nice-to-have, not
  required for v1).

## Verify
```bash
cd frontend
npx tsc -b --noEmit          # clean
npx vitest run src/dashboard # 42 passed (incl. new {seq,event} unwrap + 2-call compose fixtures)
npx vitest run               # 65 passed (whole frontend suite)
npm run build                # succeeds; emits index.html + dashboard.html
```

## Contract points consumed
§0 (base `/api`, no auth headers), §1 (campaign routes, 2-call detail, tenant-global
`/emergency-stop`, server-authoritative reflection), §2 (`{seq,event}` rows, repeated
`type`/`severity`, SSE `data.event`), §3 (escalate deferred → disabled).
