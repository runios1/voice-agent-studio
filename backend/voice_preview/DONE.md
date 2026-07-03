# P3-4 — Browser-voice preview backend — DONE

Implements the frozen `contracts/voice_preview` wire protocol as a WS route that runs
one **real** `CallEngine.run_call` per connection over a new `BrowserVoiceTransport`,
so the preview's disclosure step, in-call tools, and event trail are IDENTICAL to a
phone call — only the transport (browser PCM instead of Retell) differs.

## What's done
- **`speech_bridge.py`** — the audio<->text edge, behind a `SpeechBridge` seam:
  - `ScriptedSpeechBridge` — the CI double. Fake PCM is literal UTF-8 text (no codec
    needed); a chunk ending in `\n` finalizes the buffered lead utterance (so
    multi-chunk buffering is exercised too); `synthesize` "speaks" by chunking the
    text's UTF-8 bytes.
  - `GeminiLiveSpeechBridge` — the real Gemini 3.1 Flash Live adapter. Two Live
    sessions on purpose: an `input_audio_transcription`, `response_modalities=["TEXT"]`
    session for STT (so Live's own model never gets to originate a reply — the engine
    decides what's said, over `ModelWrapper.complete()`, same as a real call), and a
    one-shot `response_modalities=["AUDIO"]` session per agent utterance for TTS.
    **Live-smoke-test seam only** (mirrors `RetellTransport`): the `google.genai`
    import is lazy, lives only in `start()`/the streaming methods, and is never
    exercised by CI.
  - `build_speech_bridge()` — env-gated: Gemini Live once `GEMINI_API_KEY` (or
    `GOOGLE_API_KEY`) is set, else the scripted double. Same posture as
    `providers.py` / the Retell transport factory.
- **`transport.py` — `BrowserVoiceTransport`**, the frozen `CallTransport` for this
  seam. `send_agent_utterance` sends a `transcript` frame then streams the bridge's
  synthesized audio; inbound audio is **pushed in** via `push_audio`/`push_stop` from
  the router's single WS-receive loop (a socket has exactly one reader) and surfaced
  to the engine as queued `Utterance`s once the bridge finalizes a turn — the same
  queue-and-yield shape as `TextTransport`.
- **`router.py` — `create_router(config_source, registry_builder, model, sink, *,
  speech_bridge_factory=build_speech_bridge)`** — a factory exposing
  `WS /agents/{agent_id}/preview/voice` (the integrator mounts it under `/api`, per
  this package's README boundary). Per connection:
  1. Resolves the caller's own built `AgentConfig` via the injected `ConfigSource`
     (same seam as `AgentServiceConfigSource` — tenant-scoped in the caller's code,
     404 as a clean `error` frame if missing/not owned, never a stack trace).
  2. Waits for the `start` control message, then builds a preview `Lead`
     (`phone=""` — no PSTN leg), the per-agent tool registry, a fresh `CallEngine`
     over the injected model, and the transport.
  3. Runs the engine concurrently with its own inbound pump; `disclosure.spoken` and
     `lead.outcome` events are forwarded as `disclosure`/`outcome` frames via a
     `_ForwardingSink` that ALSO always forwards to the real shared `EventSink` first
     (the compliance log is unaffected by the browser dropping mid-call). Sends
     `ended` once the call finishes (or `error` + `ended` if it raised).
  - Outbound JSON + binary frames are serialized through one lock
    (`_SerializedSender`) since the engine's own task and the router's receive loop
    both write to the same socket concurrently (agent speech vs. lead transcript).

## What's mocked / injected
- **Gemini Live** — `ScriptedSpeechBridge` in every CI-run test; `GeminiLiveSpeechBridge`
  is real code, not exercised without a key + network (see live smoke test below).
- **Config source / tool registry / model** — narrow `Protocol`s
  (`ConfigSource`/`RegistryBuilder`) matching `backend.integration.config_source.
  AgentServiceConfigSource` / `backend.integration.runtime.ToolStack` exactly, so the
  integrator passes the SAME singletons the campaign orchestrator uses (one config
  artifact, one tool stack) without this package importing `backend/integration`.

## Consumed contract points
- `contracts/voice_preview/protocol.py`: the WS route, PCM format, and every JSON
  frame shape (`start`/`stop` up; `transcript`/`disclosure`/`outcome`/`error`/`ended`
  down) — followed exactly; not touched.
- `contracts/voice_runtime/interface.py`: `CallTransport`, `Utterance`.
- `contracts/campaign/model.py`: `Lead`. `contracts/events/schema.py`: `Event`,
  `EventType`. `backend/voice_runtime/engine.CallEngine`,
  `backend/voice_runtime/events.EventSink` — reused, not forked.

## Integration notes for the integrator
- Mount with the SAME singletons `integrated_app.py` already builds for campaigns:
  `create_router(AgentServiceConfigSource(service), tool_stack, model, sink)` — where
  `model`/`sink`/`tool_stack` are `app.state.model` / the shared `EventServiceSink` /
  `app.state.tool_stack` (see `backend/integration/runtime.py`, already wired into
  `SupervisedOrchestrator` the same way). Include under `/api`, matching the frozen
  route template (`/api/agents/{agent_id}/preview/voice`).
- The Live smoke test needs `GEMINI_MODEL_VOICE_LIVE` pointed at a real Live-capable
  model id (verify in the AI Studio console — preview names churn, CLAUDE.md §7);
  falls back to `gemini-3.1-flash-live`.
- Production hardening not attempted here (documented, not silently skipped): a
  dedicated background reader task decoupled from `feed_audio`'s send, so a slow
  transcription doesn't stall the next inbound chunk. Correctness doesn't depend on
  it — `BrowserVoiceTransport`'s internal queue is FIFO either way.

## How to verify
```bash
python3 -m pytest backend/voice_preview/tests/ -q   # 16 tests, no network/keys
```
Covers: `ScriptedSpeechBridge` buffering/chunking + the env-gated bridge switch;
`BrowserVoiceTransport`'s full `CallTransport` contract in isolation; and the WS route
end-to-end via `TestClient` — disclosure-first (badge frame precedes the spoken line),
the audio actually carrying the same text the transcript frame claims (not just two
independently-correct halves), a lead turn round-tripping through fake audio into an
in-call tool call and a `booked` outcome, the shared compliance sink still getting
every event even though only two of them have wire frames, and an unknown agent
producing a clean `error` frame instead of a stack trace.

### Live smoke test (Gemini Live — manual, not in CI)
Set `GEMINI_API_KEY`, run `integrated_app`, open the frontend's preview (P3-5) or any
WS client against `/api/agents/{id}/preview/voice`: send `{"type":"start"}`, stream
16kHz mono PCM s16le binary frames from a mic, confirm a `disclosure` frame arrives
before any spoken audio, a tool-enabled agent books a real slot, and `{"type":"stop"}`
yields a clean `ended` frame. The engine/disclosure/tool path is already proven by
`backend/voice_runtime`'s CI suite — only the Gemini Live wiring is new here.

## Boundaries respected
Only `backend/voice_preview/` (+ its tests) was written; `contracts/` untouched;
`CallEngine`/`EventSink` reused by import, never forked; no route mounted in
`integrated_app.py` (the integrator's job); no provider SDK imported outside a lazy
call inside `GeminiLiveSpeechBridge`.
