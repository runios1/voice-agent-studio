# P3-5 — Browser-voice preview: frontend mic UI

**Consumes:** `contracts/voice_preview`. **Paired with:** P3-4 (backend WS bridge). Reuses the
existing React app + the preview surface.

## Responsibility
- A **"Talk to your agent"** control on the preview surface that opens the WebSocket at
  `/api/agents/{agent_id}/preview/voice`, captures mic audio, and plays the agent's reply.
- Capture: getUserMedia → downsample to **16 kHz mono PCM s16le** → send as binary WS frames.
- Playback: buffer/stream incoming binary agent-audio frames to the speakers (low latency).
- Render the JSON events: live `transcript` lines (agent/lead), a **"🔒 AI disclosed"** badge on
  `disclosure`, the final `outcome`, calm inline `error` text (never a stack trace), and a
  clean close on `ended`. A visible **Hang up** button sends `stop`.

## Boundaries — do NOT
- Do **not** invent message types or audio formats — use `contracts/voice_preview` exactly.
- Do **not** touch the builder/dashboard surfaces or backend code — stay in `frontend/src/preview/`.
- Handle mic-permission denial and socket errors gracefully (the preview is a first impression).
- Keep it framework-consistent with the existing app (same state/store patterns, no new libs
  unless unavoidable for audio worklet resampling).
