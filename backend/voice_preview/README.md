# P3-4 — Browser-voice preview: backend WS bridge

**Consumes:** `contracts/voice_preview` (the wire protocol), the Phase-1/2 `CallEngine`
(`backend/voice_runtime/engine.py`), the frozen `CallTransport`. **Paired with:** P3-5 (frontend).

## Responsibility
- A WebSocket endpoint at `/api/agents/{agent_id}/preview/voice` that runs a live spoken
  conversation with the user's *built agent* in the browser.
- A `BrowserVoiceTransport` implementing the frozen `CallTransport` (`start` /
  `send_agent_utterance` / `receive` / `end`) that bridges browser PCM audio ⇄ the engine's
  text turns via **Gemini 3.1 Flash Live** (streaming STT for the mic, TTS for the reply).
- Drive the conversation with the **existing `CallEngine`** so the AI disclosure (code-emitted,
  first), in-call tools, prompt composition, and the event stream are IDENTICAL to a real call.
- Translate engine progress into the protocol's server→client JSON frames
  (`transcript` / `disclosure` / `outcome` / `error` / `ended`) and stream agent audio as binary.

## Boundaries — do NOT
- Do **not** re-implement the turn loop, disclosure, or tool execution — reuse `CallEngine`.
  If shared code must move, file a contract-change-request; don't fork it.
- Do **not** change the `contracts/voice_preview` wire format. The audio↔text bridge is your
  internal choice; the protocol is fixed.
- Keep the Gemini Live SDK lazily imported inside this package (D8 — provider SDKs never leak).
- Mount the route in `integrated_app` is the INTEGRATOR's step — expose a `create_router()` /
  factory; don't edit `integrated_app.py` from this worktree.

## Open design note (grill at dispatch)
Reuse-the-engine (STT/TTS at the transport edge) preserves disclosure/tools/events and is the
required posture. If Gemini Live's native audio dialog is used for latency, disclosure + tool
calls MUST still be enforced in code, not left to the model — do not diverge from the runtime.
