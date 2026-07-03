# INT-A — Backend Phase-2 assembly — DONE

Owner deliverable for integration stream **INT-A** of `docs/phase2-integration-plan.md`,
built to the frozen contract `contracts/dashboard_http/README.md`.

## What's done
- **`backend/phase2_app.py`** — the one FastAPI app that assembles the Phase-2 backend:
  - ONE `EventService`, wrapped by **`EventServiceSink`** (contract §4a) and threaded as
    the `OrchestratorService` sink — so a control action (pause) and produced events land
    in the SAME append-only log the dashboard reads (server-authoritative reflection).
  - `OrchestratorService(config_source=_DefaultConfigSource(), dialer=ScriptedDialer(),
    sink=EventServiceSink(events))`. The stub config source returns a default
    platform-guardrailed `AgentConfig` for any agent (the orchestrator only needs the
    LOCKED guardrails to clamp the envelope); the mock dialer never places a real dial.
  - Both routers mounted under `/api` (`orchestrator.control_api` + `events.router`);
    both typed-error handlers installed (`{"error": {...}}`, never a stack trace).
  - **Both auth deps overridden to `dev-user`** (`control_api.current_user` +
    `events.router.current_tenant`), so the frontend sends NO auth headers (contract §0).
  - **Seed (contract §4b.5):** on startup, calls INT-C's `seed_and_run(orch, events,
    tenant="dev-user", stop=...)` as a background task **if `backend.phase2_demo` is
    present**, else runs a minimal inline seed (one running campaign, 3 leads). Graceful:
    boots fine without INT-C. The demo task is stopped/cancelled on shutdown (lifespan).
  - `GET /api/health` → `{"ok": true}`.
- **`backend/tests/test_phase2_app.py`** — 9 tests, all green.

## Verify
```bash
# unit/integration tests (from repo root)
python -m pytest backend/tests/test_phase2_app.py -q

# live boot + curl (the contract §5 DONE bar)
python -m uvicorn backend.phase2_app:app --host 127.0.0.1 --port 8000
curl -s localhost:8000/api/health                                  # {"ok":true}
curl -s localhost:8000/api/campaigns                               # seeded [Campaign,...]
CID=$(curl -s localhost:8000/api/campaigns | python -c 'import sys,json;print(json.load(sys.stdin)[0]["id"])')
curl -s -X POST localhost:8000/api/campaigns/$CID/pause            # state: paused
curl -s "localhost:8000/api/events?type=campaign.paused"           # the emitted {seq,event} row
curl -sN localhost:8000/api/events/stream                          # id:/event:/data: frames
```
All of the above were run and confirmed against `uvicorn backend.phase2_app:app`.

## Stubbed / dev-only (swapped at real integration, per contract §0)
- Auth is a fixed `dev-user` (user == tenant); real session auth drops in by replacing
  the two dependency overrides — no route or client change.
- `ConfigSource` is a default-config stub (no config_gate wiring); dialer is the mock
  `ScriptedDialer` (no telephony). Both intentional for this pass.

## ⚠ Known cross-module integration bug found (NOT in INT-A's files — surfaced, not silenced)
`orchestrator/service.py::autopause` emits `EventType.CAMPAIGN_AUTOPAUSED` with
`payload={"reason": reason}`, but P2-5's `CampaignAutopausedPayload`
(`events/payloads.py`) **requires `trigger`** (`reason` is only an allowed extra). So
`orch.autopause(...)` through the shared sink fails `EventService.emit` validation:

```
POST /api/campaigns/{id}/autopause -> 422
{"error":{"kind":"event_validation","message":"Invalid payload for campaign.autopaused.","detail":"trigger: Field required"}}
```

Per contract §4a this is a real producer/adapter integration bug to **fix in the
producer, not silence in the adapter** — and it is outside INT-A's target files
(`orchestrator/service.py` / `events/payloads.py` are merged internals). **INT-A's own
DONE flows do not hit it** (authorize→`campaign.started`, pause→`campaign.paused`,
emergency-stop→`campaign.paused` all validate cleanly). But **INT-C will**: its
`seed_and_run` is required to trip `orch.autopause(...)`. Fix before/at JOIN by aligning
the producer with the payload model — either:
  - `orchestrator.autopause` emit `payload={"trigger": reason}` (and set
    `CampaignAutopausedPayload.count/window_seconds` as available), or
  - relax `CampaignAutopausedPayload` to accept `reason` instead of requiring `trigger`.
This is a one-line producer fix; flagged here so the JOIN line doesn't discover it
mid-E2E. The dashboard JOIN §5 checklist itself does not exercise autopause.
