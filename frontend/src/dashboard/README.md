# P2-7 — Dashboard frontend

**Consumes:** `contracts/events` (live subscription), the orchestrator control API
(P2-2). Reuses the existing React app.

## Responsibility
- Four view altitudes reading off the event stream: **fleet** (all campaigns + the
  global emergency stop), **campaign** (progress, live calls, outcomes),
  **live-call** (transcript/status + escalate button), **audit** (filterable,
  exportable event log).
- Live updates via the event-stream subscription (SSE/WS per P2-5).
- Kill-switch + global emergency-stop controls call the orchestrator control API and
  reflect state.

## Boundaries — do NOT
- Do not compute state client-side that belongs to the event stream — render it.
- Do not enforce control logic in the UI; call the orchestrator API (server is the
  authority). Show pause/auto-pause state and reasons from the stream.
- Stay within the dashboard area; don't touch the Phase-1 builder/preview surfaces.
