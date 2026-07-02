# P2-4 — Async workflows (post-call orchestration)

**Consumes:** `contracts/tool_registry`, `contracts/events`.

## Responsibility
- Post-call automations driven off outcome Events: confirmation email (via a
  POST_CALL registry tool), CRM write, follow-up sequences, no-answer retries.
- Honor follow-up delays; be **idempotent on replay** (the same outcome event must
  not send two emails).

## Boundaries — do NOT
- Do not compose email bodies/URLs — send approved templates via the registry only.
- Do not do in-call work (that's P2-1); you react to outcomes, latency-tolerant.
- Emit your own Events (`followup.scheduled`, `tool.invoked`) to P2-5.
