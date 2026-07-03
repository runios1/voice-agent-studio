# P4-2 — Live session runtime — DONE

`GeminiLiveAgentSession` (`session.py`), implementing the frozen `LiveAgentSession`
from `contracts/live_agent/interface.py`.

## What's done
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
  per agent turn and checked via `moderator.check()` on every delta. BLOCK cancels
  any still-buffered audio for that turn, cuts what's already playing
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
  (`transcript`/`disclosure`/`moderation`/`error`) go to `transport.send_event` — no
  frozen contract governs that second shape (P4-4 owns the wire), kept close to the
  existing `voice_preview` JSON message shapes.

## What's mocked (tests, no network)
`backend/live_agent/tests/fakes.py`: `FakeAudioTransport`, `FakeLiveConnection` +
`FakeLiveConnector` (scripted `LiveEvent` list), `FakeToolRegistry`/`FakeHandler`,
`ScriptedModerator`. `backend/live_agent/tests/test_session.py` (11 tests) proves:
disclosure-before-connect ordering, a tool round-trip (success + rejection), a
moderation BLOCK cut vs a FLAG pass-through, agent audio forwarding, native
barge-in, the DNC opt-out hard-stop, event emission + ordering, and that the
transport is always started/ended even on an empty Live stream.

`python -m pytest backend/live_agent/tests/ -q` — 11 passed, no key/SDK needed.

## Decisions made without a live grill pass (flag if you disagree)
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
5. **Event split** (audit `EventSink` vs. UI `transport.send_event`): `transcript`
   and `moderation` events are NOT in the frozen `contracts.events.EventType` enum
   (audit log has no such types) — deliberately kept on the UI channel instead of
   proposing an enum change for something that's arguably UI-only.

## Real API surface (smoke only, `# pragma: no cover` in `live_connection.py` / `speaker.py`)
`_LiveConnectionCM.__aenter__` opens `client.aio.live.connect(model=..., config=
types.LiveConnectConfig(response_modalities=["AUDIO"], system_instruction=...,
speech_config=..., input_audio_transcription=..., output_audio_transcription=...,
tools=...))`; `GeminiLiveConnection` adapts `send_realtime_input` /
`send_tool_response` / `send_client_content` / `receive()`. This SDK shape is
carried over from `GeminiLiveSpeechBridge` (STT half) plus my best understanding of
Live's function-calling + `send_client_content` API — **not yet run against a real
key in this environment**. Before relying on it: run a manual smoke (talk to it,
confirm disclosure-then-Live handoff, a tool call resolves, and a deliberately
off-guardrail ask gets cut) once `GEMINI_API_KEY` is available and P4-1 (compiler)
+ P4-3 (real moderator) are merged.

## Depends on / integrates with
- `contracts/live_agent/interface.py` (frozen) — implements `LiveAgentSession`
  exactly.
- `contracts/tool_registry/interface.py` (frozen) — `ToolRegistry`/`ToolContext`,
  same duck-typed `resolve_context` pattern as `backend/voice_runtime/engine.py`.
- `contracts/events/schema.py` (frozen) — `Event`/`EventType`/`Severity`, unchanged.
- `backend/voice_runtime/outcomes.detect_opt_out` — reused, not duplicated.
- **Not yet merged, mocked here**: P4-1's real `LiveAgentCompiler` (tests build a
  `LiveAgentSpec` by hand) and P4-3's real `StreamModerator` (tests use
  `ScriptedModerator`). Nothing in `session.py` assumes anything about either beyond
  the frozen `LiveAgentSpec` dataclass / `StreamModerator` Protocol — swapping in the
  real ones at integration should need zero changes here.
