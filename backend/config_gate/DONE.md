# WS2 — Config gate + persistence — DONE

The source-agnostic, server-side enforcement boundary (D-security) plus versioned,
tenant-scoped persistence (D10). Every config mutation — builder tool-call, manual
PATCH, or a forged request — passes through the identical `ConfigGate`.

## What's done

- **`ConfigGate`** (`gate.py`) — pure, in-memory boundary. One code path:
  1. schema/type validation (set-then-revalidate against the frozen pydantic schema),
  2. locked-path rejection (platform-locked **and** system-managed `meta.*` sub-trees;
     covers a path's descendants **and** ancestors so you can't overwrite a locked child),
  3. free-text screening on prose fields (delegated to WS5).
  On accept it recomputes `meta.status` (completeness) so READY-ness always matches content.
- **Typed error taxonomy** (`errors.py`) — emits the contract's `{ "error": {kind,path,message} }`
  shape, never a stack trace. Kinds: `locked_path`, `validation`, `screening_blocked`,
  `screening_flagged`, `rate_limited`, plus **`conflict`** and **`not_found`** (see CCR below).
- **Persistence** (`repository.py`, `postgres_repository.py`) — `ConfigRepository` Protocol with:
  - `InMemoryConfigRepository` (used by tests + the app default),
  - `PostgresConfigRepository` (Postgres **jsonb**, full-snapshot versioning; written, not run in CI).
  - **Tenant isolation in code**: every method is scoped by `owner_user_id`; a mismatch reads
    as "not found" (existence not leaked). Client-supplied identity is never trusted.
  - **Versioning**: full config snapshot per accepted mutation; `meta.version` = latest.
  - **Revert**: restores a prior snapshot as a **new** version (history stays append-only).
  - **Optimistic concurrency**: `save(expected_version=N)` → `conflict` if the latest moved.
- **Completeness** (`completeness.py`) — `required_for_ready` fields are the model; all satisfied
  → `status = READY`; emptying one drops back to `DRAFT`. `missing_required()` lists the gaps.
- **AgentService** (`service.py`) — wires gate + repo: create / get / list / patch / history / revert.
  New agents are seeded with the platform layer (locked guardrails + defaults from schema defaults).
- **FastAPI router** (`api.py`) — the endpoints WS2 owns from `api_contract.md`:
  `POST/GET /agents`, `GET /agents/{id}` (config + resolved FIELD_POLICY), `PATCH /agents/{id}/fields`,
  `GET /agents/{id}/history`, `POST /agents/{id}/revert/{version}`. `create_app()` factory.

## What's mocked / stubbed (and how it un-mocks)

- **Screening (WS5)** — `screening.py` defines `ScreeningPort`; `MockScreeningAdapter` does
  substring matching only (deterministic for tests, **not** real safety). Inject the real WS5
  adapter into `AgentService(repo, screener=...)` at integration — nothing else changes.
- **Auth** — `api.current_user` reads an `X-User-Id` header (MOCK). Replace with the real session
  dependency at integration. Tenant scoping itself is already enforced in code by the repository,
  so only the id *source* changes.
- **Postgres** — `PostgresConfigRepository` is written to the contract but not run in CI (no DB in
  the fan-out env). Live-test per below. `psycopg` is imported lazily so CI/import don't need it.

## Boundaries respected (what WS2 did NOT do)
- No model calls (the gate is model-agnostic — D-security). No builder/runtime logic.
- Did not implement `/builder/messages` (WS3) or `/preview/messages` (WS4).
- Did not edit anything under `contracts/`. The two extra error kinds live in WS2's own
  `errors.py` and are surfaced via a change request, not a silent edit.

## Contract change request filed
`docs/contract-change-requests/ws2-error-kinds.md` — adds `conflict` + `not_found` to the API
error `kind` enum and an **optional** `expected_version` on the PATCH body (additive; omitting it
preserves the frozen `{path, value}` body with last-write-wins). **Surface to the integrator.**

## Decisions taken (grill answers — user was away, took recommendations)
- Persistence: repository abstraction + in-memory (CI) + Postgres jsonb impl (production).
- HTTP surface: gate/persistence core **plus** a thin FastAPI router.
- Versioning: full snapshots (O(1) revert, jsonb-friendly).
- Concurrency: optimistic via **optional** `expected_version` (keeps the frozen body honored).

## How to verify

```bash
# From the repo root. Needs: pydantic, pytest, fastapi, httpx (installed in this env).
python -m pytest backend/config_gate/tests -q          # 50 tests, all green

# End-to-end smoke of the running gate (in-memory repo):
python -c "
from fastapi.testclient import TestClient
from backend.config_gate.api import create_app
c = TestClient(create_app()); h={'X-User-Id':'alice'}
aid = c.post('/agents', json={'name':'Acme SDR'}, headers=h).json()['meta']['id']
for p,v in [('conversation.persona.role','SDR'),('conversation.persona.tone','warm'),
            ('conversation.opening','Hi'),('conversation.primary_objective','book a call'),
            ('conversation.qualification.criteria',[{'label':'Budget'}])]:
    c.patch(f'/agents/{aid}/fields', json={'path':p,'value':v}, headers=h)
print('locked ->', c.patch(f'/agents/{aid}/fields', json={'path':'guardrails.calling_hours.start_hour_local','value':2}, headers=h).status_code)
print('reverted status ->', c.post(f'/agents/{aid}/revert/1', headers=h).json()['meta']['status'])
"
```

### Postgres impl (live, not in CI)
```python
from backend.config_gate.postgres_repository import PostgresConfigRepository
from backend.config_gate.api import create_app
repo = PostgresConfigRepository("postgresql://localhost/vas")  # needs psycopg[binary]
repo.init_schema()                 # creates agents + agent_versions (jsonb)
app = create_app(repo)             # same router, real DB
```
