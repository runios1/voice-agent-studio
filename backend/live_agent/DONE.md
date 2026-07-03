# P4-4 — Preview transport + frontend — DONE

Implements the browser `AudioTransport` (`contracts/live_agent`) as a WS route that
runs one `LiveAgentSession.run(...)` per connection, and the frontend that talks to
it. Where Phase 3's preview had to bridge browser PCM <-> a text turn loop (STT in,
TTS out), this transport has nothing to bridge — Gemini Live IS the agent, so audio
flows straight through in both directions.

## What's done

**Backend — `backend/live_agent/preview_transport.py`**
- `PreviewAudioTransport` — the frozen `AudioTransport`: `send_audio`/`recv_audio`
  pass PCM straight through; `send_event` forwards the session's event dict
  verbatim; `cut_playback()` sends a dedicated `{"type": "cut_playback"}` control
  frame (the server can't reach into the browser's `AudioContext` directly — this
  is the only way to make "silence NOW" real on the wire). Inbound audio has one
  reader (the router's own WS loop); it's pushed in via `push_audio`/`push_stop`
  into an `asyncio.Queue`, mirroring P3-4's `BrowserVoiceTransport`.
- `create_router(config_source, registry_builder, compiler, sink, *,
  session_factory, moderator_factory)` — `WS /agents/{agent_id}/preview/voice`
  (same route as the Phase-3 contract; the integrator swaps which router is
  mounted there). Per connection: resolve the caller's own built config
  (tenant-scoped, 404 as a clean `error` frame, never a stack trace); wait for
  `start`; compile the spec; build the registry; run `session.run(spec, transport,
  registry, moderator, ctx)` concurrently with the inbound pump; send `ended` with
  the returned `LiveOutcome` (or a calm `error` + `ended` if the session raised).

**Frontend — `frontend/src/preview/`** (new files, existing P3 files untouched so
the currently-mounted Phase-3 preview keeps working until the integrator retires it
per the plan's integration order):
- `livePreviewProtocol.ts` — re-exports the unchanged Phase-3 audio format/route,
  adds `ToolMessage` / `ModerationMessage` / `CutPlaybackMessage`.
- `liveVoiceSession.ts` — `LiveVoiceSession`, same shape as `VoiceSession` plus the
  three new message types and a client-inferred speaking/listening indicator (Live
  has no server-sent turn-boundary event; "agent" while audio frames are actively
  arriving, decaying to "listening" after 300ms of silence or the instant the
  user's own mic crosses the barge-in threshold).
- `LiveVoicePreview.tsx` — same shell as `VoicePreview`, plus a speaking/listening
  badge and inline tool/moderation badges.
- Reuses `audioCapture.ts` / `audioPlayback.ts` unchanged (same audio rates).

## What's mocked / injected
- `LiveAgentCompiler`, `LiveAgentSession`, `StreamModerator` (P4-1/2/3) don't exist
  yet — `create_router` takes them as required params (no defaults), and the test
  suite drives a `_ScriptedSession`/`_FakeCompiler`/`_FakeModerator` behind the
  frozen `contracts/live_agent` Protocols. `ConfigSource`/`RegistryBuilder` mirror
  `backend.integration.config_source.AgentServiceConfigSource` /
  `backend.integration.runtime.ToolStack` exactly, same seam as P3-4.

## Additive wire extension
`tool` / `moderation` / `cut_playback` are new JSON message types layered onto the
technically-frozen `contracts/voice_preview` wire — documented rather than silently
edited: `docs/contract-change-requests/p4-4-live-preview-events.md`. Existing types
and the audio format are unchanged.

## Consumed contract points
- `contracts/live_agent/interface.py`: `AudioTransport`, `LiveAgentCompiler`,
  `LiveAgentSession`, `LiveCallContext`, `LiveOutcome`, `StreamModerator`,
  `ModerationVerdict`.
- `contracts/voice_preview/protocol.py`: audio format + route + base message set
  (not touched).
- `contracts/tool_registry/interface.py`: `ToolRegistry` (type only, opaque here).
- `backend/voice_runtime/events.EventSink` — reused, not forked.

## How to verify
```bash
python3 -m pytest backend/live_agent/tests/ -q          # 13 tests, no network/keys
cd frontend && npx vitest run src/preview               # 28 tests (17 new + 11 P3, unaffected)
cd frontend && npx tsc -b                                 # clean build
```

## Integration notes for the integrator
- Mount `create_router(...)` under `/api` at the SAME route the Phase-3 router
  used, per the plan's integration order: retire the old `speech_bridge` preview
  once this is green. Pass the real `session_factory`/`moderator_factory` once
  P4-2/P4-3 land (they build a fresh instance per call — a Live session and its
  moderator both carry per-call state).
- Frontend: swap `PreviewChat.tsx`'s `VoicePreview` import for `LiveVoicePreview`
  once the backend is mounted; the old `frontend/src/preview/{voiceSession,
  VoicePreview}.*` files can then be deleted (their P4 shape now lives in the
  `live*` files).
- No real Gemini Live smoke test lives here — P4-2 owns the Live connection, so the
  live smoke belongs to that workstream. This package's own live-ness (the WS route
  + audio pass-through) has no external dependency to smoke-test; it's fully
  covered by the `TestClient` suite.

## Boundaries respected
Only `backend/live_agent/preview_transport.py` (+ its tests) and new files under
`frontend/src/preview/` were written; `contracts/` untouched (additive extension
filed as a CCR, not an edit); no route mounted in `integrated_app.py`; existing
Phase-3 preview files/tests untouched and still green; no provider SDK imported
anywhere in this package.
