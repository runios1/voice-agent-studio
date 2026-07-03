# P2-5 — Event stream + observability backbone — DONE

The single append-only stream every Phase-2 component emits to (P2-D5). Four consumers
bind to the frozen `contracts/events` schema through this package: dashboard (P2-7),
auto-pause (P2-6), the compliance audit log, and analytics. The immutable log **is**
the compliance proof — append-only is structural, not a convention.

## What's done

- **Per-type payload validation** (`payloads.py`) — the contract keeps `Event.payload`
  a generic dict on purpose and hands the per-`EventType` shape to P2-5. One pydantic
  model per event type in `PAYLOAD_MODELS`; validated at the **emit boundary** (constrain
  → validate → recover, D-reliability) so a malformed payload is rejected *before* it can
  enter the log. Compliance-critical events have **required** fields (`disclosure.spoken`
  → `text`, `guardrail.tripped` → `guardrail`, `lead.outcome` → `outcome`, `slot.booked`
  → `slot_start`). `extra="allow"` keeps payloads forward-compatible without a contract bump.
  An import-time guard fails if any `EventType` lacks a payload model.
- **Durable append-only store** (`store.py`) — `EventStore` Protocol with **no** update/
  delete method (append-only is enforced by the *shape of the interface*). `InMemoryEventStore`
  (CI + tests): thread-safe append, monotonic global `seq` (the ordering authority, since
  emitter `occurred_at` can tie/skew), deep-copy on read so a holder can't mutate the log.
  Tenant-scoped query with filters (type / severity / correlation ids / time window /
  `after_seq` cursor / limit) and `get(tenant_id, event_id)` where not-yours == not-found.
- **Live bus** (`bus.py`) — `EventBus` Protocol + `InMemoryEventBus`. Each subscriber gets a
  bounded queue with **drop-oldest-on-overflow** backpressure, so one slow subscriber can
  never block emit or leak memory (the durable log + `after_seq` replay is the authority).
  `Subscription.get(timeout=...)` is a cancel-safe timed pull (used by the SSE loop).
- **EventService** (`service.py`) — the one emit/query/subscribe door: `emit()` fills envelope
  defaults (uuid `event_id`, server-side `occurred_at`), **validates the payload**, builds the
  frozen `Event`, appends (durable) **then** publishes (live) — durability before liveness, so a
  crash can't lose an event a subscriber saw. `query` / `get` / `export_ndjson` / `subscribe`.
- **Analytics** (`analytics.py`) — **query-computed**, no second store that could drift from the
  audit record: counts by type/severity/campaign, lead-outcome and guardrail-trip tallies,
  and epoch-aligned time buckets for sparklines. Tenant-scoped via the `EventQuery` it's handed.
- **FastAPI surface** (`router.py`) — the thin router P2-7 mounts: `GET /events` (audit query
  + filter), `GET /events/export` (NDJSON download for compliance hand-off), `GET /events/analytics`,
  `GET /events/analytics/series`, and `GET /events/stream` (**SSE** — D10). The stream **backfills
  from the durable store after the client's last seq, then tails the live bus**, subscribing
  *before* the backfill and deduping by seq → a **no-gap / no-dupe** guarantee across the
  backfill↔live seam. Disconnect-polled with a heartbeat so a gone client tears down instead
  of leaking a subscription. Auth is a mock `X-Tenant-Id` header (same pattern as config_gate).
- **Typed errors** (`errors.py`) — `EventError` / `EventValidationError` emit the same
  `{ "error": {kind, message, detail} }` shape as the config gate; never a stack trace.

## What's mocked / stubbed (and how it un-mocks)

- **Postgres** (`postgres_store.py`) — `PostgresEventStore` + `PostgresListenBus`, same seams as
  the in-memory impls, **written to the contract but NOT run in CI** (no DB in the fan-out env —
  identical posture to config_gate's `PostgresConfigRepository`). `psycopg` (v3) is imported
  **lazily** so the package imports cleanly without the driver. Append-only is enforced **in the
  database** by a `BEFORE UPDATE OR DELETE` trigger that raises (defense in depth behind the
  no-mutation API), and live fan-out uses **LISTEN/NOTIFY** (a per-tenant channel carrying the new
  seq; subscribers read the rows back by seq — the DB stays the single source, no new infra).
  Swap in via `EventService(store=PostgresEventStore(dsn), bus=PostgresListenBus(store))`.
- **Auth** — `current_tenant` reads `X-Tenant-Id` (MOCK). The integrator overrides it with the
  real session dep; tenant scoping itself is already enforced in code, so only the id *source* changes.
- **httpx ASGITransport can't drive an infinite SSE response** (it buffers whole responses), so the
  stream body is the extracted, directly-tested `event_sse_stream(...)` generator rather than an
  HTTP round-trip. The non-streaming endpoints are covered via `TestClient`.

## Boundaries respected (what P2-5 did NOT do)
- **No domain logic.** Auto-pause detection is P2-6 (it only *reads* this stream); orchestration
  is P2-2. This package emits, persists, serves, and aggregates — nothing more.
- **No mutation path.** There is deliberately no update/delete anywhere (API and DB trigger).
- **Tenant is always present and always enforced in code** — no unscoped query or subscribe.
- **Did not edit `contracts/`.** The frozen `Event` envelope is consumed as-is; the per-type
  payload models live here (the contract explicitly delegates them to P2-5). No CCR needed.

## Grill decisions taken (user said "you decide" — took all recommendations)
- Bus/persistence: **Postgres LISTEN/NOTIFY (prod) + in-memory async pub/sub (CI)** — simplest
  thing giving both a durable append-only log *and* live subscribe in the DB we already run.
- Payload validation: **per-type model registry, validated on emit**; envelope stays generic.
- Immutability: **no-mutation API + DB trigger**; **monotonic seq** for total order; **no
  retention-delete** (the audit log is the compliance proof — kept indefinitely).
- Live transport: **SSE** (D10). Analytics: **query-computed, no separate store**.
- Emit ergonomics: an `emit(...)` helper fills `event_id`/`occurred_at`; `tenant_id` mandatory.

## How to verify

```bash
# From the repo root. Needs: pydantic, fastapi, pytest, httpx (installed in this env).
python -m pytest backend/events/tests -q          # 39 tests, all green

# End-to-end smoke of the running backbone (in-memory store, HTTP router):
python - <<'PY'
import asyncio, json
from fastapi.testclient import TestClient
from contracts.events.schema import EventType, Severity
from backend.events import EventService, create_app, EventQuery
svc = EventService()
async def trail():
    await svc.emit(EventType.DISCLOSURE_SPOKEN, tenant_id="acme", call_id="k1", payload={"text":"This is an AI assistant."})
    await svc.emit(EventType.GUARDRAIL_TRIPPED, tenant_id="acme", severity=Severity.WARNING, payload={"guardrail":"dnc"})
    await svc.emit(EventType.LEAD_OUTCOME, tenant_id="acme", payload={"outcome":"qualified"})
    await svc.emit(EventType.CALL_STARTED, tenant_id="globex", payload={})   # other tenant — must not leak
asyncio.run(trail())
c = TestClient(create_app(svc)); H={"X-Tenant-Id":"acme"}
print("audit (acme only):", [r["event"]["type"] for r in c.get("/events", headers=H).json()])
print("analytics:", c.get("/events/analytics", headers=H).json())
print("export lines:", len([l for l in c.get("/events/export", headers=H).text.splitlines() if l]))
PY
```

### Postgres impl (live, not in CI)
```python
from backend.events import EventService, PostgresEventStore, PostgresListenBus
store = PostgresEventStore("postgresql://localhost/vas")  # needs psycopg[binary]
store.init_schema()   # events table (jsonb) + append-only trigger + NOTIFY trigger
svc = EventService(store=store, bus=PostgresListenBus(store))  # same router, real DB
```

## Integration notes (for the integrator)
- Mount `create_router(service)` into the one app under the API prefix; override `current_tenant`
  with the real session dep. Inject `PostgresEventStore`/`PostgresListenBus` for production.
- Every emitter (P2-1/2/3/4/6) calls `EventService.emit(...)`; auto-pause (P2-6) and the dashboard
  (P2-7) consume via `subscribe(...)` / the `/events/stream` SSE endpoint and `query(...)`.
- Merge order per the plan: **P2-5 merges first** (foundational).
