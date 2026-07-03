"""FROZEN CONTRACT — the browser <-> backend live-voice preview protocol (Phase 3).

The "talk to your agent" preview: the user speaks into their browser mic and hears the agent
reply, over a single WebSocket. This is a NEW seam, so both sides depend on it — the backend
bridge (**P3-4**) and the frontend mic UI (**P3-5**) — and it must be frozen before either
starts.

Design intent (do NOT let the impl drift from this):
  * The preview MUST reuse the Phase-1/2 `CallEngine` turn loop so the code-emitted AI
    disclosure, prompt composition, in-call tools, and the event stream are IDENTICAL to a
    real call. The browser is just another `CallTransport` (`BrowserVoiceTransport`) — audio
    at the edges, the same text turn loop inside. How audio<->text is bridged (Gemini Live
    streaming STT/TTS) is P3-4's internal choice; it does NOT change this wire protocol.
  * Audio is raw PCM, so the browser needs no codec: 16 kHz, mono, signed 16-bit
    little-endian. Frames are sent as BINARY WebSocket messages. Everything else (control,
    transcript, lifecycle) is JSON TEXT messages with a `type` field.

Route (owned by the integrator when P3-4 mounts it; fixed here so P3-5 can target it):

    WS  /api/agents/{agent_id}/preview/voice

Auth: dev is the fixed dev user (no header), same as every other route today; real session
auth drops in behind the same dependency without a protocol change.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

# --- audio format (both directions) ------------------------------------------------------ #
AUDIO_SAMPLE_RATE_HZ = 16_000
AUDIO_CHANNELS = 1
AUDIO_SAMPLE_FORMAT = "pcm_s16le"  # signed 16-bit little-endian
WS_ROUTE_TEMPLATE = "/api/agents/{agent_id}/preview/voice"

# Binary frames carry audio. JSON text frames carry everything below (discriminated on `type`).


# --- client -> server (JSON control) ----------------------------------------------------- #
class StartMessage(BaseModel):
    """First message the client sends to open the conversation. The server then starts the
    CallEngine over a BrowserVoiceTransport and begins streaming agent audio back (the
    disclosure is spoken first, in code)."""

    type: Literal["start"] = "start"


class StopMessage(BaseModel):
    """Client asks to end the call (user clicked 'Hang up' / closed the mic)."""

    type: Literal["stop"] = "stop"


# Binary client->server frames are lead-mic audio in AUDIO_SAMPLE_FORMAT. No JSON envelope.


# --- server -> client (JSON events; binary frames are agent audio) ------------------------ #
class TranscriptMessage(BaseModel):
    """A finalized line of the conversation, for on-screen display. `role` is who spoke."""

    type: Literal["transcript"] = "transcript"
    role: Literal["agent", "lead"]
    text: str


class DisclosureMessage(BaseModel):
    """Emitted when the mandatory AI-disclosure line has been spoken (mirrors the
    DISCLOSURE_SPOKEN event). Lets the UI badge 'AI disclosed'."""

    type: Literal["disclosure"] = "disclosure"


class OutcomeMessage(BaseModel):
    """The call reached an outcome (booked / qualified / not_qualified / ...)."""

    type: Literal["outcome"] = "outcome"
    outcome: str


class ErrorMessage(BaseModel):
    """A recoverable problem, surfaced conversationally — never a stack trace."""

    type: Literal["error"] = "error"
    message: str


class EndedMessage(BaseModel):
    """The server has ended the call and will send nothing further before closing the socket."""

    type: Literal["ended"] = "ended"
    outcome: Optional[str] = None
