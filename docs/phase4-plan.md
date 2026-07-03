# Phase 4 — Live-native conversational agent (the pivot)

## Why
The text-brain + TTS path can't be conversational: measured ~3s to first audio (the TTS
model is generative, not real-time, and doesn't stream). Gemini Live is ~1s, natural,
interruptible, and calls tools natively. A product whose pitch is "voice AI that makes calls
that make sense" has to sound like a real call — so **Gemini Live becomes the agent**, and we
keep the load-bearing security parts AROUND it.

## The architecture (and what we keep)
Live drives the conversation. The security spine is relocated, not discarded:
- **Tools guarded in code** — Live *requests* a function; the existing `ToolHandler` still
  enforces allowlists/caps/calling-hours/approved-templates server-side. Unchanged.
- **Disclosure scripted in code** — a fixed line is spoken *before* Live gets the mic (a
  prompt instruction can be skipped/injected; a legal requirement can't rely on that).
- **Output moderation as the net** — Live's output transcription is screened with a small
  audio buffer so a violation can be cut before (most of) it is spoken. Reduces harm; not the
  floor. Because tools + disclosure are bounded, it only polices *what it says*.

The "massive shift" is just WHO drives the turns. Carried over unchanged: config schema,
builder, guarded tool handlers, event stream/audit, orchestrator, connections/OAuth.

## Hard facts (measured this session — bake in, don't re-derive)
- Live model id (this key): **`gemini-3.1-flash-live-preview`**. Live REJECTS TEXT modality
  (API 1007) — audio-native (`response_modalities=["AUDIO"]`).
- Audio: **16 kHz** mono PCM in, **24 kHz** mono PCM out. First-audio ~1s.
- Live has native VAD/turn-taking + barge-in + function-calling; `input/output_audio_transcription`
  give the text to render and to moderate.
- Env: `GEMINI_API_KEY` set; `GEMINI_MODEL_VOICE_LIVE` overrides the model.

## Frozen contract (the whole critical path)
`contracts/live_agent/` — `LiveAgentSpec` + `LiveAgentCompiler`, `AudioTransport`,
`StreamModerator` + `ModerationVerdict`, `LiveAgentSession` + `LiveCallContext` + `LiveOutcome`.
Everything else it needs (`config_schema`, `tool_registry`, `events`, `voice_preview` wire) is
already frozen.

## Workstreams (fan out — each its own worktree + branch)

| # | Workstream | Path | Depends on |
|---|---|---|---|
| **P4-1** | Agent compiler: config → `LiveAgentSpec` (system instruction + **closing directions** + disclosure line + Live tool declarations) | `backend/live_agent/compiler.py` | live_agent contract, config_schema, tool_registry catalog |
| **P4-2** | Live session runtime: connect Live, pipe audio, route function-calls → guarded handlers, scripted disclosure, emit events, integrate moderator | `backend/live_agent/session.py` | live_agent contract, wrapper_impl (Gemini access) |
| **P4-3** | Streaming output moderation: `StreamModerator` over the security screener + buffering/verdict | `backend/live_agent/moderation.py` | live_agent contract, security |
| **P4-4** | Preview transport + frontend: browser `AudioTransport` (WS) + UI (speaking/listening, disclosure, tool + moderation events) | `backend/live_agent/preview_transport.py`, `frontend/src/preview/` | live_agent contract, voice_preview wire |
| **P4-5** | Closing directions in config + builder: an (additive, optional) structured place for wrap-up behavior so the compiler has real material | `contracts/config_schema` (additive), `backend/builder_loop` | config_schema |
| **P4-6** | Phone bridge (deferrable): run the SAME Live session on a real call (Retell custom-LLM path or SIP) | `backend/live_agent/phone_transport.py` | P4-2, voice_runtime/Retell |

P4-1/2/3 are backend-isolated. P4-4 splits backend WS vs `frontend/src/preview`. P4-5 is an
additive schema+builder change (do early — P4-1 consumes it; until it lands P4-1 compiles from
existing fields + a stub closing field). P4-6 can wait for a green preview.

## Integration order (after merge)
1. **P4-5** (closing field) — additive, unblocks the compiler's real material.
2. **P4-1 + P4-3** — compiler + moderator (both pure-ish, keyless-testable).
3. **P4-2** — the session; wire compiler + moderator + registry. Live smoke: talk to it.
4. **P4-4** — mount the browser transport route in `integrated_app`; the preview now runs the
   Live agent. E2E: fast natural call, disclosure first, a tool books, moderation can cut.
5. Retire the old STT/TTS `speech_bridge` preview path once P4-4 is green (keep the guarded
   handlers + events).
6. **P4-6** — phone, when ready.

## Decisions baked in (say so if you disagree before freeze)
- Moderation screens **output transcription** text with a fixed `moderation_buffer_ms` audio
  delay; BLOCK cuts + steers. (Not token-level; simple + good enough.)
- Closing directions start as an **additive optional** config field, compiled into the system
  instruction — not a rewrite of the schema.
- Real phone runs the **same** `LiveAgentSession` behind a phone `AudioTransport` (P4-6),
  keeping preview and phone on one runtime.

## Guardrails carried into Phase 4
Tool execution stays in the guarded handlers; disclosure spoken in code; secrets/tenant
isolation server-side; provider SDKs lazily imported. The moderator is allowed to fail — it is
never the only thing between the model and the caller.
