# FROZEN CONTRACT — Dashboard ⇄ Phase-2 backend HTTP surface (v1)

The seam between the **dashboard frontend** (P2-7, `frontend/src/dashboard/`) and the
**Phase-2 backend assembly** (the running FastAPI process). It exists because two
integration workstreams must agree without touching each other's files:

- **INT-A** (backend assembly) must *serve* exactly these routes.
- **INT-B** (frontend reconciliation) must *call* exactly these routes.

Neither reads the other's code. Both read THIS. Freeze before dispatch; a change here
is cross-cutting (announce it, like any `contracts/` change).

This contract does not invent backend behavior — it pins the surface the **already-
merged** routers expose (`backend/orchestrator/control_api.py`, `backend/events/
router.py`) and the adaptations the frontend must make to consume them. Underlying
object shapes are the frozen `contracts/campaign/model.py` (`Campaign`, `Lead`) and
`contracts/events/schema.py` (`Event`) — not restated here.

---

## 0. Ground rules

- **Base path:** all routes are served under `/api` (the Vite dev proxy forwards
  `/api` → `:8000` unchanged, as in Phase 1).
- **Dev auth (v1):** the assembly **overrides the auth dependencies server-side** to a
  single fixed dev identity where `user == tenant` (call it `dev-user`). Therefore the
  **frontend sends NO auth headers** in v1 (`fetch(..., {credentials:"same-origin"})`,
  no `X-User-Id` / `X-Tenant-Id`). Real session auth drops in later without a route or
  client change. INT-A MUST honor this (override `orchestrator.control_api.current_user`
  **and** `events.router.current_tenant` to return `dev-user`).
- **Error shape:** typed JSON `{"error":{...}}` at the router's status code (already
  emitted by both routers' installed handlers). The frontend surfaces `error.message`
  conversationally; never a stack trace.
- **Discoverability (already wired on master):** the two surfaces are separate HTML
  entries/roots — the builder studio (`index.html`) and the dashboard (`dashboard.html`)
  — cross-linked in their headers (Studio → "Operations dashboard ↗" → back "← Agent
  studio"), both emitted by the Vite build. A human reaches the dashboard from the main
  app; no endpoint knowledge needed. INT-B preserves this; it is not a per-request seam.

---

## 1. Campaigns (orchestrator control API — P2-2)

| Method | Path | Body | Response |
|---|---|---|---|
| `GET`  | `/api/campaigns` | — | `Campaign[]` |
| `GET`  | `/api/campaigns/{id}` | — | `Campaign` |
| `GET`  | `/api/campaigns/{id}/leads` | — | `Lead[]` |
| `POST` | `/api/campaigns/{id}/pause` | — | `Campaign` (now `paused`) |
| `POST` | `/api/campaigns/{id}/resume` | — | `Campaign` (now `running`) |
| `POST` | `/api/emergency-stop` | — | `{"stopped": true}` |

- `Campaign` / `Lead` are the frozen `contracts/campaign/model.py` shapes,
  `model_dump(mode="json")`. `Campaign.state ∈ {draft,running,paused,completed}`;
  `Campaign.autopause_reason` is the reason surfaced on the dashboard.
- **Campaign detail is TWO calls.** The frontend's `getCampaign(id)` composes
  `CampaignDetail = { campaign: GET /campaigns/{id}, leads: GET /campaigns/{id}/leads }`.
- **`emergencyStopAll` → `POST /api/emergency-stop`** (tenant-global; NOT per-campaign,
  NOT `/control/emergency-stop`). It pauses every RUNNING campaign and emits a
  `campaign.paused` (severity `critical`, `payload.reason="emergency_stop"`) per campaign.
- **Reflection is server-authoritative.** `pause`/`resume`/`emergency_stop` each **emit
  a `campaign.*` event** onto the stream (§2). The dashboard must NOT flip campaign state
  on the click — it flips when the event arrives on the live stream (existing store
  behavior via `applyLifecycle`). The POST responses may be used to clear the `pending`
  flag but not to mutate state ahead of the stream.
- **Out of frontend scope (do not call):** `POST /api/campaigns` (authorize),
  `POST /api/campaigns/{id}/autopause` (the P2-6 hook), `POST /api/emergency-stop/clear`.
  Seeding/authorizing is INT-A/INT-C's job, not the dashboard's.

---

## 2. Events (event backbone — P2-5)

| Method | Path | Query | Response |
|---|---|---|---|
| `GET` | `/api/events` | filter (below) | `Row[]` |
| `GET` | `/api/events/stream` | filter + `after_seq` | SSE, one `Row` per frame |
| `GET` | `/api/events/export` | filter | `application/x-ndjson` (one `Row`/line) |

Where **`Row = { "seq": number, "event": Event }`** — the event is **wrapped**, never
bare. `seq` is the monotonic durable-log sequence.

**Filter query params (repeatable):**
- `type` — repeat once per event type, e.g. `?type=call.started&type=call.ended`
  (**NOT** a comma-joined `types=`). Values are `EventType` strings.
- `severity` — repeat per severity (`info`|`warning`|`critical`).
- `campaign_id`, `lead_id`, `call_id`, `agent_id` — single.
- `since`, `until` — ISO-8601 datetimes.
- `after_seq` — integer; the stream/query returns only `seq > after_seq`.
- `limit` — integer (query only).

**SSE frame shape** (from `/api/events/stream`):
```
id: <seq>
event: event
data: {"seq": <seq>, "event": { ...Event... }}

```
The stream **replays** the durable backfill (everything after `after_seq`) then attaches
the live tail, with a no-gap/no-dupe guarantee. `id:` carries `seq`.

**Frontend adaptations (INT-B):**
- `queryAudit(filter)` → `GET /api/events?…`, then **map each row to `row.event`** to get
  `Event[]`. Serialize `types[]`→ repeated `type`, `severity`→ repeated `severity`.
- `subscribeEvents(filter)` → `GET /api/events/stream?…`; in `rawToEvent`, read the Event
  from **`data.event`** (currently it reads `data` directly). Optionally track the last
  `seq` and pass it as `after_seq` on reconnect (nice-to-have, not required for v1).
- Audit **Export** may either keep the current client-side JSON export of the loaded
  rows, OR (preferred) link to `GET /api/events/export` for the server NDJSON. Either
  satisfies v1; pick one and note it.

---

## 3. Escalate — DEFERRED in v1

There is **no** `POST /api/calls/{id}/escalate` route. Live-call escalation is a
voice-runtime / tool-registry action (P2-D6) and is **out of the v1 HTTP contract**.

- **Frontend (INT-B):** in real (non-mock) mode, the escalate control is **disabled with
  a "not available in this build" title**, or hidden. Do not call a non-existent route.
- If escalate is wanted later, it is a follow-up contract addition (a new route +
  voice-runtime wiring), not part of this freeze.

---

## 4. Backend assembly seam (INT-A) — internal, but frozen so INT-C can plug in

The assembly builds **one** `EventService` and threads it everywhere as the sink, so a
control action and a produced call event land in the **same** log the dashboard reads.

**(a) EventSink adapter.** Emitters (orchestrator, and optionally voice-runtime) depend
on a tiny `EventSink` with `async emit(event: Event) -> None` (see
`backend/orchestrator/events.py`). The `EventService.emit(...)` API takes a *type +
kwargs* and validates/persists/publishes. INT-A provides the adapter:

```python
class EventServiceSink:                    # adapts P2-5 EventService -> orchestrator EventSink
    def __init__(self, service: EventService) -> None: self._svc = service
    async def emit(self, event: Event) -> None:
        await self._svc.emit(
            event.type, tenant_id=event.tenant_id, payload=event.payload,
            severity=event.severity, campaign_id=event.campaign_id,
            lead_id=event.lead_id, call_id=event.call_id, agent_id=event.agent_id,
            event_id=event.event_id, occurred_at=event.occurred_at,
        )
```
⚠ `EventService.emit` **validates payload per type** (`backend/events/payloads.py`). If a
producer's payload fails validation, that is a real integration bug to fix in the
producer/adapter — surface it, don't silence it (both sides were built to the same frozen
events contract, so they should align).

**(b) App factory.** `backend/phase2_app.py` exposing `app` (run:
`uvicorn backend.phase2_app:app --port 8000`). Responsibilities, in order:
1. one `EventService()`; wrap as `EventServiceSink`.
2. `OrchestratorService(config_source=<stub or config_gate>, dialer=<mock>, sink=<adapter>)`
   — a stub `ConfigSource` returning a default `AgentConfig` is sufficient (the service
   only needs the locked guardrails to clamp the envelope); the mock dialer from
   `backend/orchestrator/mocks.py` is fine (the dashboard E2E does not require real dials).
3. mount `orchestrator.control_api.create_router(orch)` and `events.router.create_router(events)`
   under `/api`; install both error handlers.
4. **override auth deps** to `dev-user` (both, per §0).
5. **seed:** call `seed_and_run(orch, events, tenant="dev-user")` from INT-C if present;
   otherwise fall back to a minimal inline seed (authorize 1 campaign with a few leads so
   the fleet is non-empty). INT-A MUST run without INT-C (graceful fallback).
6. `GET /api/health` → `{"ok": true}`.

**(c) Demo-scenario entrypoint (INT-C).** Frozen signature INT-A calls and INT-C
implements:
```python
async def seed_and_run(
    orch: OrchestratorService,
    events: EventService,
    *,
    tenant: str = "dev-user",
    stop: Optional[asyncio.Event] = None,
) -> None: ...
```
It authorizes ≥1 campaign (via `orch.authorize_campaign`) and drives simulated live
motion — call lifecycle events (`call.started`→`disclosure.spoken`→`tool.invoked`→
`slot.booked`→`lead.outcome`→`call.ended`) emitted through `events.emit(...)`, plus at
least one `orch.autopause(...)` trip — on a timer until `stop` is set. It shares the SAME
`orch`/`events` instances the app serves, so the browser sees the motion live. It must be
unit-testable against in-memory instances with NO HTTP.

---

## 5. What "done" looks like at the join (sequential, after A/B/[C])

Run `uvicorn backend.phase2_app:app --port 8000` and
`cd frontend && VITE_USE_MOCK=false npm run dev`, open `/dashboard.html`:
fleet lists the seeded campaign(s); the event trail ticks live; **Pause flips the
campaign to `paused` via the stream** (not the click) and the `campaign.paused` event
appears in the Audit log; Emergency-stop halts all; Audit filter/export works. (Escalate
disabled per §3.)
