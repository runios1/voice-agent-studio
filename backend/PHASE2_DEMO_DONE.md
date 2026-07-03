# INT-C — Demo scenario + live producers — DONE

## What's done
- **`backend/phase2_demo.py`** implements the frozen contract §4c entrypoint:
  `async def seed_and_run(orch, events, *, tenant="dev-user", stop=None) -> None`
  (plus an optional `beat_seconds` pacing knob, default 1.5s, that tests set to 0).
  - Authorizes **one** demo campaign (`orch.authorize_campaign`) with 5 leads.
  - Drives a realistic, repeating call lifecycle onto the **shared** `events`:
    `call.started → disclosure.spoken → tool.invoked(check_calendar[/book_slot]) →
    slot.booked → lead.outcome → call.ended`, with a believable spread of outcomes
    (qualified / not_qualified / no_answer / callback_requested).
  - Trips the kill switch each pass: emits a `guardrail.tripped` burst, calls
    `orch.autopause(...)` (→ `campaign.autopaused`, CRITICAL), then `orch.resume(...)`
    (→ `campaign.resumed`) so the fleet visibly flips PAUSED→RUNNING and keeps moving.
  - Shares the passed-in `orch`/`events` (never builds its own), so dashboard control
    actions and produced events land in one log. Loops until `stop` is set; runs a
    single terminating pass if called with no `stop` (safety valve).
  - Every payload validates at the `EventService.emit` boundary (compliance-critical
    fields present: disclosure `text`, `slot_start`, `outcome`, `guardrail`).

- **`backend/tests/test_phase2_demo.py`** — 4 tests, no HTTP, driving `seed_and_run`
  against in-memory `OrchestratorService` (sink → `EventService`, per §4a adapter) +
  `EventService`:
  1. full lifecycle + `campaign.autopaused` land (proves control & produced events
     share the log);
  2. campaign authorized with the demo name + 5 leads;
  3. all payloads pass emit-boundary validation (compliance fields persisted);
  4. no-`stop` call runs exactly one pass and terminates (no hang).

## Contract points consumed
- §4c frozen `seed_and_run` signature (INT-A calls it; falls back if absent).
- §4a `EventServiceSink` adapter shape (replicated in the test to wire orch→events
  without importing INT-A's not-yet-merged `phase2_app.py`).
- `EventService.emit(type, **kwargs)` (P2-5), `OrchestratorService.authorize_campaign
  / list_leads / autopause / resume / get_campaign` (P2-2), `backend/events/payloads.py`
  per-type payload shapes.

## Cross-cutting change — READ BEFORE MERGE (announced per D14)
Fixing a **real, pre-existing integration bug** that INT-C is the first to exercise:
`CampaignAutopausedPayload.trigger` was REQUIRED, but **no** producer emits it
(orchestrator sends `reason`; P2-6 sends `rule`+`reason`), so every `campaign.autopaused`
emit failed validation at the real `EventService` — breaking the JOIN and real P2-6.
- **CCR:** `docs/contract-change-requests/int-C.md`.
- **Fix (one file, P2-5 impl, not a frozen `contracts/` file):**
  `backend/events/payloads.py` — made `trigger` optional and recognized `rule`/`reason`.
  Matches the module's own compliance-field policy (`campaign.autopaused` is not in the
  REQUIRED set). No producer changed; no events test regressed.

## Verify
```bash
python -m pytest backend/tests/test_phase2_demo.py -q      # 4 passed
python -m pytest backend/events backend/orchestrator backend/autopause -q   # 97 passed (payloads fix regresses nothing)
```

## Stubbed / not in this pass
- No real telephony/tools — the call lifecycle is simulated (as the plan specifies).
- Auto-pause runs as a direct `orch.autopause` trip, not a live P2-6 stream consumer
  (explicitly deferred in the plan).
- `EventServiceSink` is INT-A's to own in `phase2_app.py`; the copy here is test-only.
