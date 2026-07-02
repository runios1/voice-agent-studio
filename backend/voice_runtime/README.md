# P2-1 — Voice runtime

**Consumes:** `contracts/voice_runtime`, `contracts/tool_registry`,
`contracts/events`. **Called by:** P2-2 (orchestrator).

## Responsibility
- Implement `VoiceRuntime`: run a call for a (config, lead) over a `CallTransport`
  (managed platform — Retell v1 — + Gemini Live), keeping the Phase-1 shared parts
  identical (code-emitted disclosure step, prompt composition).
- Execute **IN_CALL** registry tools live; enforce their guardrails via the handler.
- **Warm transfer-to-human** (`escalate`) on defined conditions (P2-D6).
- Emit `call.*`, `disclosure.spoken`, `slot.booked`, `lead.outcome` Events (P2-5).

## Boundaries — do NOT
- Do not rewrite the turn loop — **reuse** the shared logic from `runtime_loop`
  (disclosure, compiler, tools). If shared code must move to a common spot, file a
  contract-change-request and let the integrator do the refactor — don't fork it in
  your worktree.
- Provider-agnostic: keep the voice platform behind `CallTransport` (Retell→LiveKit
  swap, D9). Platform may be mocked in CI.
