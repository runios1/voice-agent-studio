# contracts/voice_preview — FROZEN (Phase 3)

The browser ⇄ backend live-voice protocol for the "talk to your agent" preview.

- **Depended on by both sides:** the backend WS bridge (**P3-4**, `backend/voice_preview/`)
  and the frontend mic UI (**P3-5**, `frontend/src/preview/`).
- **Route:** `WS /api/agents/{agent_id}/preview/voice` (mounted by the integrator).

**Wire format:** binary WebSocket frames carry raw PCM audio (16 kHz, mono, s16le) both ways;
JSON text frames carry control + lifecycle, discriminated on `type` (`start`/`stop` up;
`transcript`/`disclosure`/`outcome`/`error`/`ended` down). See `protocol.py`.

**Non-negotiable design intent:** the preview reuses the existing `CallEngine` turn loop, so
the AI disclosure, in-call tools, and event stream are identical to a real call. The browser
is just a `BrowserVoiceTransport` implementing the frozen `CallTransport`. The audio↔text
bridge (Gemini Live) is P3-4's internal choice and MUST NOT change this wire protocol.

Changing the wire format is a **contract-change-request**.
