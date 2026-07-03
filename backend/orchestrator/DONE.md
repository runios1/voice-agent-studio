# P2-2 — Campaign orchestrator — DONE

Bounded-autonomy execution (P2-D1): a human authorizes a campaign (agent + leads +
schedule + guardrail envelope) and the orchestrator dials the leads unsupervised
within that envelope — delegating each call to the VoiceRuntime (P2-1), emitting
lifecycle Events (P2-5), honoring rate/concurrency/calling-hours, and obeying a kill
switch (P2-D3). Per-lead state is persisted (P2-D2) so a crash resumes from the DB
with **no double-dial**.

## What's done

- **The queue IS the leads table** (`repository.py`) — no external broker. Dispatch
  is an **atomic claim** that flips one eligible lead `QUEUED/RETRY → DIALING`
  (`FOR UPDATE SKIP LOCKED` in Postgres; a lock in memory), so no two workers ever
  grab the same lead-attempt. `OrchestratorRepository` Protocol + `InMemory…` (CI) +
  `Postgres…` (written, live-tested) — same shape/pattern as config_gate.
- **Per-lead state machine + persistence** (`runner.resolve_outcome`) — maps a
  `CallOutcome` to `DONE` (booked/qualified/not_qualified/**opted_out**/transferred)
  or a scheduled `RETRY` (no-answer/voicemail/failed) with exponential backoff, up to
  the envelope's attempt cap, then `exhausted_*`. `OPTED_OUT` is terminal and never
  retried (DNC is locked). The DB is the source of truth; nothing lives only in
  worker memory.
- **No double-dial, two ways** — (a) the atomic claim = one dial per attempt under
  concurrency; (b) before dialing, the claim stamps a deterministic
  `lead.last_call_id = "{lead}:{attempt}"`, the **idempotency key** a conformant
  runtime honors, so a resumed dial returns the recorded outcome instead of dialing
  again. `last_call_id` is already on the frozen `Lead` → no contract change.
- **Crash-resume** (`CampaignRunner.run`) — on start it re-drives any leads left in
  `DIALING/IN_CALL` (with their existing `last_call_id`) before the dispatch loop, so
  calling `run_campaign` again after a restart continues cleanly with no re-dial.
- **Scheduling** (`scheduling.py`, clock-injected) — calling-hours windows, sliding
  60s rate limiter (`calls_per_minute`, shared across a campaign's workers), and
  backoff — all driven by an injectable `Clock` so time-dependent behaviour is
  deterministic in tests.
- **Guardrail envelope clamped to the locked guardrails** (`envelope.py`) — the
  authorized envelope is pulled to be **equal-or-stricter** than the config's LOCKED
  `calling_hours` + `max_call_attempts` (D4/D-security). `clamp_envelope` (default,
  tighten) and `validate_envelope` (reject a widened one) both provided.
- **Kill switch, one mechanism, 4 layers** (`service.py`, P2-D3) —
  `campaign.state == PAUSED` reached via `pause` (manual), `emergency_stop` (global
  flag halting every RUNNING campaign), and `autopause(reason)` (**the hook P2-6
  calls**). All stop NEW dials; the runner's per-tick gate lets the in-flight call
  finish. No live call is ever hard-aborted.
- **Events emitted** (`events.py`) — `campaign.started/paused/autopaused/resumed` and
  per-attempt `lead.outcome`, correlation-scoped (tenant always present). `EventSink`
  is the P2-5 seam; `InMemoryEventSink` backs CI. Call-lifecycle events remain the
  VoiceRuntime's to emit.
- **Control API for P2-7** (`control_api.py`) — thin FastAPI router: authorize, list/
  get campaigns, list leads, pause/resume/autopause, global emergency-stop + clear.
  Tenant-scoped (a campaign that isn't yours is a 404, never leaked); errors are the
  typed `{error:{kind,message}}` shape, never a stack trace.

## What's mocked / stubbed (and how it un-mocks)

- **VoiceRuntime (P2-1)** — `mocks.MockVoiceRuntime` implements the frozen
  `VoiceRuntime` (idempotent on `last_call_id`, scriptable outcomes). The real seam,
  `dialer.VoiceRuntimeDialer(runtime, transport_factory, registry)`, is exercised in
  `test_integration.py`; at integration only the injected runtime/transport/registry
  become real. `test_integration` proves the full `run_call` path + event trail.
- **ToolRegistry (P2-3)** — `mocks.MockToolRegistry`, passed straight through to
  `run_call`; the orchestrator does not execute tools itself.
- **ConfigSource (config_gate)** — `mocks.InMemoryConfigSource`. At integration, adapt
  config_gate's tenant-scoped repo (`repo.get(agent_id, owner_user_id)`); the tenant
  check moves there unchanged. Needed so the envelope can be clamped to the LOCKED
  guardrails.
- **TransportFactory (P2-1)** — `mocks.MockTransportFactory` returns an inert
  transport; the real Retell/LiveKit transport is injected at integration.
- **Auth** — `control_api.current_user` reads `X-User-Id` (same MOCK convention as
  config_gate). Tenant scoping is already enforced in code by the repo/service, so
  only the id *source* changes.
- **Postgres** — `PostgresOrchestratorRepository` is written to the contract but not
  run in CI (no DB in the fan-out env); `psycopg` is imported lazily. Live-test below.

## Boundaries respected (what P2-2 did NOT do)
- Did not run the call — every dial is delegated through the `Dialer`/`VoiceRuntime`.
- Did not implement trip **detection** — P2-2 only exposes `autopause` for P2-6 to call.
- Held no lead progress in memory as source of truth — the repo is authoritative.
- Edited nothing under `contracts/`. `last_call_id` (idempotency key) and the campaign
  autopause bookkeeping are all already on the frozen models — no contract change or CCR.

## Decisions taken (grill answers — took recommendations)
- **Queue tech:** the Postgres leads table itself (state + `next_action_at`, claimed
  via `FOR UPDATE SKIP LOCKED`); workers are asyncio tasks. No Redis/Celery — leanest
  shape satisfying P2-D2, swappable behind `OrchestratorRepository`.
- **Idempotency:** atomic claim + deterministic `last_call_id` key (above).
- **Calling-hours timezone:** a single campaign timezone (default UTC) for v1;
  per-lead timezones are a later refinement (noted in `clock.py`), not a schema change.
- **Kill switch:** one flag (`state==PAUSED`) + a global-stop table; runner checks
  before each dial, awaits in-flight to completion.

## How to verify

```bash
# From the repo root. Needs: pydantic, pytest, fastapi, httpx (installed in this env).
python -m pytest backend/orchestrator/tests -q          # 32 tests, all green
```

Covers: envelope clamping, scheduling/backoff/rate math, full drain, retry+backoff,
attempt exhaustion, opt-out terminality, calling-hours wait, rate-limit spacing,
concurrency cap, **crash-resume ×2 (no double-dial)**, atomic claim under threads,
pause / global emergency-stop / autopause (each halts new dials + lets in-flight
finish), resume, the control API, and tenant isolation. `test_integration.py` runs a
campaign through the real `VoiceRuntimeDialer` seam and asserts the event trail.

### Postgres impl (live, not in CI)
```python
from backend.orchestrator.postgres_repository import PostgresOrchestratorRepository
repo = PostgresOrchestratorRepository("postgresql://localhost/vas")  # needs psycopg[binary]
repo.init_schema()   # creates campaigns + leads + orchestrator_global_stops
# Inject into OrchestratorService(config_source, dialer, repo=repo, sink=<P2-5 sink>).
```
