# CR: three additive JSON message types for the Live-native preview
- **Workstream:** P4-4 — Preview transport + frontend
- **Contract affected:** `contracts/voice_preview/protocol.py` (the frozen Phase-3
  wire, reused unchanged per `contracts/live_agent/README.md`)
- **Status:** proposed (implemented in this workstream without editing the frozen
  file — see "Workaround" below)

## Problem
`contracts/live_agent/interface.py`'s `LiveAgentSession` (P4-2, not yet built) needs
to tell the browser UI three things the Phase-3 vocabulary (`transcript`/
`disclosure`/`outcome`/`error`/`ended`) has no shape for:

1. A tool the agent invoked (`tool_declarations` are Live-native now — the model
   calls a function directly, so the UI needs its own event to badge "used
   calendar" the way it used to infer this from engine-authored transcript text).
2. A streaming-output-moderation verdict (`StreamModerator`, P4-3) — FLAG (soft,
   logged) vs. BLOCK (cuts the utterance) — so the UI can show "guardrail caught
   something" instead of silently truncating the agent's voice.
3. `AudioTransport.cut_playback()` (a frozen method on the contract, called
   separately from `send_event`) needs *some* wire signal — the server can't reach
   into the browser's `AudioContext` directly — telling the client to flush audio
   it already has scheduled, the instant a BLOCK fires.

The audio format and `start`/`stop`/`ended` lifecycle are unaffected.

## Proposed change
Three new server -> client JSON message shapes, additive only (existing types
untouched, so old clients — if any still exist post-integration — safely ignore an
unrecognized `type` the same way `VoiceSession.handleMessage`'s switch already does):

```python
class ToolMessage(BaseModel):
    type: Literal["tool"] = "tool"
    name: str
    timing: Literal["in_call", "post_call"]

class ModerationMessage(BaseModel):
    type: Literal["moderation"] = "moderation"
    verdict: Literal["flag", "block"]

class CutPlaybackMessage(BaseModel):
    type: Literal["cut_playback"] = "cut_playback"
```

## Blast radius
- **P4-2** (session): the producer — must call `transport.send_event({"type": "tool", ...})`
  on a tool call and `{"type": "moderation", "verdict": ...}` after `StreamModerator.check`,
  and `transport.cut_playback()` (separately) on BLOCK.
- **P4-4** (this workstream): the consumer on both ends — `PreviewAudioTransport.send_event`
  forwards any dict verbatim (no shape enforcement needed on the Python side); the
  frontend's Live preview renders the three new types alongside the existing ones.
- No other workstream (P4-1, P4-3, P4-5, P4-6) touches the wire directly.

## Workaround while pending
Implemented directly rather than blocking on contract sign-off, because the change
is purely additive (no existing field/type is altered) and both producer-shape and
consumer-shape live in workstreams this same author can keep in sync:
`backend/live_agent/preview_transport.py`'s module docstring documents the exact
three dict shapes above as the contract P4-2 must emit through, and
`frontend/src/preview/livePreviewProtocol.ts` mirrors them in TypeScript. If P4-2
lands with a different shape, that's a follow-up fix to whichever side is wrong, not
a redesign — same posture as P4-5's additive `config_schema` touch.
