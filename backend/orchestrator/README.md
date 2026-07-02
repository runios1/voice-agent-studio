# P2-2 — Campaign orchestrator

**Consumes:** `contracts/campaign`, `contracts/events`. **Depended on by:** P2-1 (it
calls the runtime), P2-6 (trips its kill switch), P2-7 (control API).

## Responsibility
- Queue + workers; **per-lead state persisted in Postgres** (resume-from-DB after
  crash; idempotent, **no double-dial**, P2-D2).
- Scheduling, concurrency + rate limits, calling-hours — honored via `attempts` +
  `next_action_at`. The `GuardrailEnvelope` may only be equal-or-stricter than the
  locked guardrails.
- The **kill-switch mechanism** (P2-D3): one state flag workers honor —
  campaign pause + global emergency stop + auto-pause hook. On stop: **no new calls,
  let in-flight finish.** Expose a small control API for P2-7.
- Emit lifecycle Events (campaign/lead) to P2-5.

## Boundaries — do NOT
- Do not run the call yourself — delegate to the `VoiceRuntime` (P2-1).
- Do not hold lead progress only in memory; the DB is the source of truth.
- Do not implement pattern-detection (that's P2-6; you just expose the kill switch).
