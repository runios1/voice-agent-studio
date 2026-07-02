# P2-4 — Async workflows — DONE

Post-call automation: reacts to `lead.outcome` events from the stream and runs
platform-authored, idempotent workflows (confirmation email, CRM write, delayed
follow-up touches) against the tool registry, emitting `tool.invoked` /
`followup.scheduled` back to the stream.

## What's done
- **Self-built runner behind an interface** (`engine.py`) — P2-D2's "n8n-style"
  choice: workflows are DATA (`models.py`), executed by `LocalWorkflowEngine`, which
  implements the `WorkflowEngine` protocol so a durable engine (Temporal/n8n) can
  replace it later without touching the dispatcher/scheduler. One language, no infra.
- **Event-driven dispatch** (`dispatcher.py`) — subscribes to the stream (P2-D5
  routing) and reacts only to `lead.outcome`; a declarative `RoutingTable` maps the
  outcome to a workflow. Non-outcome events and unrouted outcomes are no-ops, never
  errors. The outcome's `event_id` is the run's idempotency root.
- **Idempotent on replay** (`idempotency.py`) — every side-effecting step is fenced
  by a `(run_id, index, tool)` key via an atomic `check_and_record`. At-least-once
  redelivery of the same outcome sends exactly one email; a run that crashes mid-way
  resumes (done steps skip, remaining run). In-memory ledger; Postgres-shaped seam.
- **Delays + backoff honored** (`scheduler.py`, `backoff.py`, `clock.py`) — SCHEDULE
  steps park a `ScheduledAction` at a `run_at`; `tick()` fires the due ones. Time is
  read through an injectable `Clock`, so tests advance a `ManualClock` (no real
  sleep). No-answer touches use exponential-capped backoff and STOP once the lead's
  attempts hit the envelope's `max_attempts_per_lead`.
- **Guardrails at the tool boundary** — the engine never composes an email body/URL;
  a step carries only an approved `template_id`, and the (mock) handler REJECTS any
  unapproved template in code (D6/D-security). The engine never picks a tenant:
  `ToolContext` is built from the trigger and the per-tenant connection is resolved
  by an injected resolver.
- **Emits its own events** (`events_out.py`) — `tool.invoked` per side effect and
  `followup.scheduled` per deferred touch, correlation ids stamped from the trigger,
  back-linked to the origin outcome via `origin_event_id`.
- **Default automations** (`defaults.py`) — booked→confirm+CRM, qualified→CRM+nurture
  touch (24h), no_answer/voicemail→backoff touch, opted_out→CRM only (never email).
- **Runnable demo** (`demo.py`) — drives booked + no_answer, a replay, and a
  clock-advance that fires the delayed touch.

## What's mocked (consumed contracts — swap at integration)
- **Tool registry (P2-3)** — `mocks.MockToolRegistry` implements the frozen
  `ToolRegistry`/`RegistryTool`/`ToolHandler`/`ToolContext` with POST_CALL `email` +
  `crm` handlers. Real registry + handlers slot in unchanged.
- **Per-tenant connections (P2-3)** — `mocks.MockConnectionResolver` (frozen
  `Connection`). Real one enforces tenant isolation over encrypted tokens.
- **Event stream (P2-5)** — `mocks.InMemoryEventSink` is the write side; the outcome
  feed (`fixtures.outcome_event`) stands in for a live subscription. Both use the
  frozen `Event` envelope only.

## Consumed contract points
- `contracts/events/schema.py`: `Event`, `EventType.{LEAD_OUTCOME, TOOL_INVOKED,
  FOLLOWUP_SCHEDULED}`, `Severity`.
- `contracts/tool_registry/interface.py`: `ToolRegistry`, `RegistryTool`,
  `ToolContext`, `Connection`, `Timing.POST_CALL`.
- `contracts/campaign/model.py`: `GuardrailEnvelope.max_attempts_per_lead` (backoff bound).

## Boundaries respected
- No email body/URL composition — approved `template_id` via the registry only.
- No in-call work (that's P2-1) — strictly latency-tolerant post-call reactions.
- No re-dialing — a no-answer schedules a follow-up *touch*; re-dialing stays the
  orchestrator's `LeadState.RETRY` (P2-2). Contracts untouched (read-only).

## How to verify
Run from the worktree root.

```bash
python3 -m pytest backend/async_workflows/tests/ -q      # 14 tests
python3 -m backend.async_workflows.demo                   # end-to-end drive
```

Expected from the demo: `booked` sends one confirmation email + CRM write and emits
two `tool.invoked`; `no_answer` sends nothing yet, emits one `followup.scheduled`;
replaying `booked` sends nothing new; advancing the clock 2h fires the deferred
`sorry_we_missed_you` touch (a third `tool.invoked`).

## Notes / for the integrator
- `tick()` is a manual pump for tests/demo; production wires it to a periodic poller
  (or a durable timer) over a `run_at`-indexed table — the `ScheduleStore` seam.
- Outcome→workflow routing + the workflow library are platform defaults in
  `defaults.py`; per-campaign overrides drop in by constructing `RoutingTable` /
  `WorkflowLibrary` differently — no engine change.
- The dispatcher currently takes events one-by-one via `handle()`; connect it to
  P2-5's subscription transport (SSE/stream) at integration.
