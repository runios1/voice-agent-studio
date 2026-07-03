# backend/live_agent — Phase 4 — DONE

This package holds the whole Live-native agent (`contracts/live_agent`), built by
several parallel workstreams. Each section below is one workstream's handoff note,
kept intact rather than collapsed into a single narrative.

## P4-3 — Streaming output moderation (`moderation.py`)
No dedicated handoff doc was written for this stream — see the module docstring in
`moderation.py` for the design (cumulative + debounced screening over
`backend.security.engine.screen_text`, sticky BLOCK per utterance, utterance-reset
detection). `DebouncedStreamModerator` / `build_stream_moderator` satisfy the frozen
`StreamModerator` Protocol that P4-2 (below) is written against.

## P4-1 — Agent compiler (`compiler.py`)

`LiveAgentCompilerImpl.compile(config) -> LiveAgentSpec` (`compiler.py`). Config in,
compiled Live spec out — pure, deterministic, no network, no SDK.

### What's done
- **`system_instruction`** — same precedence rule as the Phase-1/2 text-brain
  compiler (`backend/runtime_loop/compiler.py`): LOCKED platform guardrails first,
  declared to override everything below and anything the caller says; user
  persona/goal after, framed as operating within the rails; a closing lock footer.
  `wishlist` is never rendered (D13).
- **CLOSING directions** (new section vs. the text-brain compiler) — qualified ->
  confirm missing details -> book (if calendar enabled) -> mention the automatic
  confirmation email (if email enabled too) -> sign off; a graceful non-qualified
  exit; a no-tools-enabled fallback that still states a concrete next step in
  words. Which branch fires is gated on enabled automation (the real capability
  signal), so an agent that never touches P4-5's `conversation.closing` behaves
  exactly as before. When `closing` carries real material — `confirm_fields`,
  `confirmation_template_id`, `sign_off` — it refines the wording without changing
  which branch fires. `closing.book_meeting` is deliberately NOT used as a gate
  (see the module docstring): gating on it would silently suppress booking
  language for pre-P4-5 agents, since it defaults `False`.
- **`disclosure_line`** — delegated to `backend.runtime_loop.guardrails.disclosure_line`
  (not reimplemented): one source of truth for the exact code-emitted legal
  utterance, reused the same way `voice_runtime` already does.
- **`tool_declarations`** — least-privilege JSON-schema dicts (`{name, description,
  parameters}`) for each ENABLED, **IN_CALL** tool in
  `backend.tool_registry.catalog.DEFAULT_CATALOG`. Disabled automation -> no
  declaration (structural denial, unchanged). Email is POST_CALL in the catalog —
  intentionally **never** declared to Live; it runs as an async workflow after the
  call ends, same as Phase 2 (`backend/voice_runtime/tools.py` filters the same
  way). The closing section talks about the email narratively; Live never calls it.

### What's mocked / not touched
- No Live session, no transport, no moderator — this module only produces the
  `LiveAgentSpec` dataclass the session (P4-2) consumes.
- No google.genai import anywhere in this file.

### Consumed contract points
- `contracts/live_agent/interface.py`: `LiveAgentSpec`, `LiveAgentCompiler` Protocol.
- `contracts/config_schema/schema.py`: `AgentConfig` (persona, qualification,
  objections, voicemail, disclosure, guardrails, automation.{calendar,email}).
- `contracts/tool_registry/interface.py`: `RegistryTool`, `Timing`.
- `backend/tool_registry/catalog.py`: `DEFAULT_CATALOG` (read-only).
- `backend/runtime_loop/guardrails.py`: `disclosure_line` (reused, not duplicated).
- Tests reuse `backend/runtime_loop/fixtures.py:sample_ready_config` (same pattern
  `voice_runtime`'s tests already use) rather than duplicating a fixture builder.

### Boundaries respected
- No route mounting, no session runtime, no moderator implementation.
- Did not edit the frozen `contracts/live_agent/` interface.
- Did not touch `contracts/config_schema` (P4-5's job) — noted the seam instead.

### How to verify
```bash
python3 -m pytest backend/live_agent/tests/ -q   # 22 tests (P4-1 only, before P4-2 landed)
python3 -m pytest backend/live_agent/ backend/runtime_loop/ backend/tool_registry/ backend/builder_loop/ backend/config_gate/ -q  # 171 tests, nothing collateral broke
```

## P4-2 — Live session runtime (`session.py`) — the core

`GeminiLiveAgentSession` (`session.py`), implementing the frozen `LiveAgentSession`
from `contracts/live_agent/interface.py`.

### What's done
- **Disclosure spoken in code before Live connects** (`speaker.py`'s `Speaker`,
  bypassing Live entirely — Live is conversational and would reply to a line it's
  asked to "say," not read it verbatim, same reasoning as `GeminiLiveSpeechBridge`).
  Proven by an ordering test (`speak()` happens before the connector is entered).
- **Live connection normalized to a small internal seam** (`live_connection.py`):
  `LiveConnection` (`send_audio` / `send_tool_response` / `send_steer` / `receive`)
  + `LiveEvent`. `session.py` is written against this, not `google.genai` — CI never
  imports the SDK; `GeminiLiveConnection`/`default_live_connector` are the real
  adapter, exercised only by the documented live smoke (below).
- **Function-call round-trip**: a Live function call resolves a `ToolContext` via
  `registry.resolve_context` (duck-typed fallback to bare correlation ids, same
  pattern as `CallEngine._execute_tool`) and runs the GUARDED handler; a rejection
  becomes `GUARDRAIL_TRIPPED` + an error result fed back to Live (never a crash); a
  `booked: True` result sets `LiveOutcome.BOOKED` + emits `SLOT_BOOKED`.
- **Streaming output moderation integration**: output transcription is accumulated
  per agent turn and checked via `moderator.check()` on every delta (P4-3's
  `DebouncedStreamModerator` satisfies this directly). BLOCK cancels any
  still-buffered audio for that turn, cuts what's already playing
  (`transport.cut_playback()`), emits `GUARDRAIL_TRIPPED` (reason
  `moderation_block`), and steers Live back on guardrail (`send_steer`). FLAG is
  logged to the transport (`{"type": "moderation", ...}`) but never interrupts —
  the moderator is a net, not the floor.
- **Moderation delay buffer**: each agent audio chunk is held for
  `spec.moderation_buffer_ms` (a per-chunk scheduled task) before being forwarded,
  so a BLOCK detected from the (typically slightly-ahead) transcript can cancel it
  before it's heard. Buffered audio still outstanding when the call ends *naturally*
  is flushed, not dropped.
- **Native barge-in**: Live's own `interrupted` signal on `server_content` triggers
  `transport.cut_playback()`.
- **DNC opt-out — the one turn-loop guardrail NOT delegated to Live** (decision
  made without a live grill session, flagged here rather than silently baked in):
  input transcription is accumulated per turn and screened with the same
  `detect_opt_out` heuristic `CallEngine` uses (`backend.voice_runtime.outcomes`,
  reused, not duplicated). A hit ends the call immediately: cuts Live off, speaks a
  fixed acknowledgement via the same code `Speaker` (never routed through the
  model), sets `LiveOutcome.OPTED_OUT`. Rationale: a Live-driven turn loop has no
  other interception point for a legally-critical guardrail that must not depend on
  a persona choosing to honor it (D-security).
- **Outcome determination**: `BOOKED` / `OPTED_OUT` are set by the events above;
  otherwise `QUALIFIED` if the caller ever said anything (transcribed), else
  `NO_ANSWER` — same coarse-fallback posture as `HeuristicOutcomeClassifier`.
  `FAILED` on any unhandled internal exception (caught in `run()`, never surfaced as
  a crash — D-reliability).
- **Events**: `events.py` mirrors `backend/voice_runtime/events.py`'s `EventSink` /
  `CollectingEventSink` seam, adapted to `LiveCallContext` (which has no `call_id` —
  `run()` mints one per conversation). Audit-log-shaped events
  (`CALL_STARTED`/`DISCLOSURE_SPOKEN`/`TOOL_INVOKED`/`GUARDRAIL_TRIPPED`/
  `SLOT_BOOKED`/`LEAD_OUTCOME`/`CALL_ENDED`) go to the `EventSink`; UI-shaped events
  (`transcript`/`disclosure`/`tool`/`moderation`/`error`) go to `transport.send_event`
  — no frozen contract governs that second shape; P4-4 owns the wire and documents
  the exact dict shapes in a CCR (see the P4-4 section below). The `tool` event was
  added to this file at P4-4's merge to close that gap (P4-2 originally only logged
  tool calls to the `EventSink`, with nothing on the UI wire).

### What's mocked (tests, no network)
`backend/live_agent/tests/fakes.py`: `FakeAudioTransport`, `FakeLiveConnection` +
`FakeLiveConnector` (scripted `LiveEvent` list), `FakeToolRegistry`/`FakeHandler`,
`ScriptedModerator`. `backend/live_agent/tests/test_session.py` (11 tests) proves:
disclosure-before-connect ordering, a tool round-trip (success + rejection), a
moderation BLOCK cut vs a FLAG pass-through, agent audio forwarding, native
barge-in, the DNC opt-out hard-stop, event emission + ordering, and that the
transport is always started/ended even on an empty Live stream.

`python -m pytest backend/live_agent/tests/ -q` — with P4-1/3 now merged too, the
whole package's suite (compiler + moderation + session) runs together; see
"How to verify" below for the combined count.

### Decisions made without a live grill pass (flag if you disagree)
1. **Steering** on a moderation BLOCK is a generic, hardcoded system-style note
   (`STEER_INSTRUCTION` in `session.py`) sent via `LiveConnection.send_steer` — never
   echoes the blocked text back into Live's context.
2. **`LiveConnection.send_steer`** is an addition to the internal (non-frozen)
   connection seam, not `contracts/live_agent`. Implemented on the real adapter via
   `session.send_client_content(...)` — unverified against the live API; part of the
   smoke.
3. **Escalation (warm transfer) is out of scope.** `LiveOutcome` has no `TRANSFERRED`
   member and `AudioTransport` has no transfer hook — there's no contract surface to
   escalate through yet. Not silently worked around. If a human-request heuristic is
   wanted before P4-6 (phone bridge), it needs a CCR extending `LiveOutcome` and/or
   `AudioTransport`.
4. **Lead-utterance boundary heuristic**: since Live signals only the *agent's* turn
   completion (`turn_complete`), not the caller's, a caller utterance is treated as
   "finalized" (emitted as a `transcript` event, cleared) the moment the agent's
   *next* reply starts producing output transcription. Good enough for
   disclosure/opt-out/transcript UX; not exact turn-boundary science.
5. **Event split** (audit `EventSink` vs. UI `transport.send_event`): `transcript`,
   `tool`, and `moderation` events are NOT in the frozen `contracts.events.EventType`
   enum (audit log has no such types) — deliberately kept on the UI channel instead
   of proposing an enum change for something that's arguably UI-only.

### Real API surface (smoke only, `# pragma: no cover` in `live_connection.py` / `speaker.py`)
`_LiveConnectionCM.__aenter__` opens `client.aio.live.connect(model=..., config=
types.LiveConnectConfig(response_modalities=["AUDIO"], system_instruction=...,
speech_config=..., input_audio_transcription=..., output_audio_transcription=...,
tools=...))`; `GeminiLiveConnection` adapts `send_realtime_input` /
`send_tool_response` / `send_client_content` / `receive()`. This SDK shape is
carried over from `GeminiLiveSpeechBridge` (STT half) plus my best understanding of
Live's function-calling + `send_client_content` API — **not yet run against a real
key in this environment**. Before relying on it: run a manual smoke (talk to it,
confirm disclosure-then-Live handoff, a tool call resolves, and a deliberately
off-guardrail ask gets cut) once `GEMINI_API_KEY` is available.

### Depends on / integrates with
- `contracts/live_agent/interface.py` (frozen) — implements `LiveAgentSession`
  exactly.
- `contracts/tool_registry/interface.py` (frozen) — `ToolRegistry`/`ToolContext`,
  same duck-typed `resolve_context` pattern as `backend/voice_runtime/engine.py`.
- `contracts/events/schema.py` (frozen) — `Event`/`EventType`/`Severity`, unchanged.
- `backend/voice_runtime/outcomes.detect_opt_out` — reused, not duplicated.
- **P4-1's `LiveAgentCompilerImpl`** (`compiler.py`) and **P4-3's
  `DebouncedStreamModerator`** (`moderation.py`) are now both merged alongside this;
  `session.py` was written only against their frozen dataclass/Protocol shapes
  (`LiveAgentSpec`, `StreamModerator`) and needed zero changes to integrate with
  the real implementations — tests still use `ScriptedModerator`/hand-built specs
  for speed and to keep the moderator's screener dependency out of this suite.

## P4-4 — Preview transport + frontend

Implements the browser `AudioTransport` (`contracts/live_agent`) as a WS route that
runs one `LiveAgentSession.run(...)` per connection, and the frontend that talks to
it. Where Phase 3's preview had to bridge browser PCM <-> a text turn loop (STT in,
TTS out), this transport has nothing to bridge — Gemini Live IS the agent, so audio
flows straight through in both directions.

### What's done

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

### What was mocked while building, reconciled at merge
This workstream started before P4-1/2/3 existed, so its own tests drive a
`_ScriptedSession`/`_FakeCompiler`/`_FakeModerator` behind the frozen
`contracts/live_agent` Protocols — those fakes stay (they're the whole point of
testing `preview_transport.py` in isolation). At merge time the *real* P4-2
(`GeminiLiveAgentSession`) was found not to emit a `tool` UI event at all (only
`TOOL_INVOKED` to the `EventSink`), which would have silently made this
workstream's tool badge dead code. Fixed directly in `session.py::
_handle_function_calls` (one `transport.send_event({"type": "tool", "name":
call.name, "timing": "in_call"})` per call, right after `TOOL_INVOKED` is emitted —
`timing` is always `"in_call"` here since Live is only ever declared IN_CALL tools,
per P4-1's compiler) rather than left as a known gap, since P4-2's own docstring
assigns UI-wire-shape ownership to P4-4.
`ConfigSource`/`RegistryBuilder` mirror `backend.integration.config_source.
AgentServiceConfigSource` / `backend.integration.runtime.ToolStack` exactly, same
seam as P3-4.

### Additive wire extension
`tool` / `moderation` / `cut_playback` are new JSON message types layered onto the
technically-frozen `contracts/voice_preview` wire — documented rather than silently
edited: `docs/contract-change-requests/p4-4-live-preview-events.md`. Existing types
and the audio format are unchanged. (`disclosure` also gained a `text` field from
the real P4-2 — additive, ignored by clients that don't read it.)

### Consumed contract points
- `contracts/live_agent/interface.py`: `AudioTransport`, `LiveAgentCompiler`,
  `LiveAgentSession`, `LiveCallContext`, `LiveOutcome`, `StreamModerator`,
  `ModerationVerdict`.
- `contracts/voice_preview/protocol.py`: audio format + route + base message set
  (not touched).
- `contracts/tool_registry/interface.py`: `ToolRegistry` (type only, opaque here).
- `backend/voice_runtime/events.EventSink` — reused, not forked.

### How to verify
```bash
python3 -m pytest backend/live_agent/tests/ -q          # whole package, this workstream's suite included
cd frontend && npx vitest run src/preview               # 28 tests (17 new + 11 P3, unaffected)
cd frontend && npx tsc -b                                 # clean build
```

### Integration notes for the integrator
- Mount `create_router(...)` under `/api` at the SAME route the Phase-3 router
  used, per the plan's integration order: retire the old `speech_bridge` preview
  once this is green. Real factories: `session_factory=lambda: GeminiLiveAgentSession(sink)`,
  `moderator_factory=build_stream_moderator` (or equivalent) — a fresh instance per
  call, since both carry per-call state.
- Frontend: swap `PreviewChat.tsx`'s `VoicePreview` import for `LiveVoicePreview`
  once the backend is mounted; the old `frontend/src/preview/{voiceSession,
  VoicePreview}.*` files can then be deleted (their P4 shape now lives in the
  `live*` files).
- No real Gemini Live smoke test lives here — P4-2 owns the Live connection, so the
  live smoke belongs to that workstream. This package's own live-ness (the WS route
  + audio pass-through) has no external dependency to smoke-test; it's fully
  covered by the `TestClient` suite.

### Boundaries respected
Only `backend/live_agent/preview_transport.py` (+ its tests), one added line in
`session.py` (see above, applied at merge to close a real interoperability gap
between two already-built workstreams), and new files under
`frontend/src/preview/` were written; `contracts/` untouched (additive extension
filed as a CCR, not an edit); no route mounted in `integrated_app.py`; existing
Phase-3 preview files/tests untouched and still green; no provider SDK imported
anywhere in this package.

## How to verify (whole package, post-merge)
```bash
python3 -m pytest backend/live_agent/ -q
```
