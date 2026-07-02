# P2-6 — Auto-pause / escalation engine

**Consumes:** `contracts/events`; **calls:** the orchestrator kill-switch (P2-2).

## Responsibility
- Detect trip patterns over the event stream (e.g. N `guardrail.tripped` in a window,
  anomalies) → **trip the campaign kill switch** and emit `campaign.autopaused`
  (P2-D3). This is where the Q1/Q3 hard-stops live.
- Fire **escalations** on defined conditions; apply **debounce/cooldown** so a
  flapping signal can't thrash campaigns.

## Boundaries — do NOT
- Do not own the pause *mechanism* — you invoke P2-2's kill switch, you don't
  reimplement it.
- Read-only over the event stream; do not mutate events.
- Keep thresholds/rules configurable; don't hard-code magic numbers inline.
