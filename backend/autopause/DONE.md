# P2-6 — Auto-pause / escalation engine — DONE

Read-only consumer of the event stream that detects trip patterns and, through
narrow ports, invokes P2-2's kill switch, emits `campaign.autopaused`, or pages a
human. Stays entirely inside `backend/autopause/`; `contracts/` untouched.

## What's done

- **Event-time windowed detection** (`windows.py`) keyed by `(tenant_id, campaign_id)`
  — deterministic, replay-safe, tenant-isolated (D-security).
- **Declarative rule chain** (`rules.py`), thresholds all in `config.py` (no inline
  magic numbers — README boundary):
  - `GuardrailTripRule` — N `guardrail.tripped` in a window → **AUTOPAUSE** (the core
    P2-6 pattern / P2-D3).
  - `CriticalGuardrailRule` — one CRITICAL `guardrail.tripped` → **AUTOPAUSE now**
    (compliance breach: undisclosed AI, DNC).
  - `EscalationSpikeRule` — M `call.escalated` in a window → **ESCALATE** to a human.
- **Engine** (`engine.py`): runs the chain per event; on an un-suppressed signal it
  trips the kill switch + emits `campaign.autopaused`, or escalates. **Debounce /
  cooldown** per `(action, campaign)` on event-time stops flapping; a
  `campaign.resumed` event **re-arms** detection. Never blocks in-flight calls — it
  flips the flag and lets P2-2 drain live calls (P2-D3).
- **Closed-enum respected:** emits only `campaign.autopaused` (in the frozen enum);
  escalations route out-of-band via the `Escalator` port — no invented event types.
- **Config loading seam:** `EngineConfig.from_dict` (future per-tenant/DB policy);
  ignores unknown keys so a newer policy blob can't crash an older engine.

## What's mocked (not yet merged — reached only via `ports.py`)

- **P2-2 kill switch** → `KillSwitch` port, faked by `RecordingKillSwitch`.
- **P2-5 event-stream emit + live subscribe** → `EventSink` port +
  `InMemoryEventStream` (a `subscribe`/`publish` fan-out matching `engine.attach`).
- **Human escalation channel** → `Escalator` port, faked by `RecordingEscalator`.

At integration these three constructor args are swapped for the real adapters; no
engine change.

## Verify

```bash
# from repo root
python -m pytest backend/autopause/ -q          # 26 passed
```

Runnable-surface proof (the /verify surface = live consumption): `test_engine.py::
test_attach_consumes_a_live_stream` drives the engine off a live
`InMemoryEventStream` — publishing 3 guardrail trips trips the kill switch and emits
one `campaign.autopaused`, exactly as it will off the real P2-5 bus.

Covered by tests: threshold trip, below-threshold no-op, single-CRITICAL immediate
pause, escalation spike (no pause), cooldown anti-flap, resume re-arm, cooldown
expiry re-trip, tenant/campaign isolation, campaign-less events ignored, window
eviction/boundary, `from_dict` merge/unknown-key tolerance.

## Not in scope (future)

- Richer anomaly heuristics (no-answer rate, sentiment) — add a rule + config
  section; engine loop unchanged.
- Persisting cooldown state across an engine restart (currently in-memory; on
  restart it re-reads the durable stream, so worst case is a redundant pause on an
  already-paused campaign, which P2-2 treats idempotently).
