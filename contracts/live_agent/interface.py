"""FROZEN CONTRACT — the Live-native conversational agent (Phase 4).

The pivot: instead of a text brain (`CallEngine`) + separate STT + slow TTS, the agent IS
Gemini Live (audio-in -> reasoning -> audio-out, ~1s, natural, interruptible). Live drives
the conversation and calls tools natively; we keep the load-bearing parts of the security
model AROUND it:

  * TOOLS stay guarded in CODE — Live only *requests* a function; the existing
    `ToolHandler` still enforces allowlists / caps / calling-hours / approved templates
    server-side (contracts/tool_registry). The strongest guarantee survives untouched.
  * DISCLOSURE stays scripted in CODE — a fixed line is spoken BEFORE Live gets the mic
    (a prompt instruction can be skipped/injected; a legal requirement cannot rely on that).
  * OUTPUT MODERATION is the net, not the floor — Live's output transcription is screened
    with a small audio buffer so a violation can be cut before (most of) it is spoken. It
    reduces harm; it does not prevent it. Because tools + disclosure are bounded above, the
    moderator only has to police WHAT IT SAYS.

So the "massive shift" is really just WHO drives the turns — moved from a code loop into
Live. The config schema, builder, guarded tool handlers, event stream, orchestrator, and
connections all carry over unchanged.

Hard facts learned live (bake into impls, do NOT re-derive):
  * Live model id (this key): `gemini-3.1-flash-live-preview`. Live REJECTS a TEXT response
    modality (API 1007) — it is audio-native (`response_modalities=["AUDIO"]`).
  * Audio: INPUT 16 kHz mono PCM s16le; Live OUTPUT is 24 kHz mono PCM. Do not conflate.
  * Live has built-in VAD/turn-taking + barge-in and supports native function-calling.
  * `input_audio_transcription` / `output_audio_transcription` give the text streams to
    render and to moderate. First-audio latency ~1s.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, Optional, Protocol

from contracts.config_schema.schema import AgentConfig
from contracts.tool_registry.interface import ToolRegistry


# --------------------------------------------------------------------------- #
# 1. The compiled agent — everything a Live session needs, derived from a config.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class LiveAgentSpec:
    """The AgentConfig, compiled for Live. Produced by `LiveAgentCompiler` (P4-1),
    consumed by the session (P4-2). Pure data — no live objects — so it is trivially
    testable and cacheable."""

    system_instruction: str            # persona + conversation guardrails + CLOSING directions
    disclosure_line: str               # spoken in code BEFORE Live drives (never a prompt hope)
    tool_declarations: list[dict]      # Live FunctionDeclarations (JSON schema) for ENABLED tools
    voice_name: str = "Kore"           # prebuilt Live voice
    model: Optional[str] = None        # default resolved from env (gemini-3.1-flash-live-preview)
    moderation_buffer_ms: int = 600    # how long output audio is held for screening


class LiveAgentCompiler(Protocol):
    """config -> LiveAgentSpec. The one place agent policy becomes a Live prompt +
    tool set. Owns the CLOSING directions (qualified -> confirm details -> book -> email
    -> sign off) and the disclosure line. (P4-1)"""

    def compile(self, config: AgentConfig) -> LiveAgentSpec: ...


# --------------------------------------------------------------------------- #
# 2. Audio transport — the medium under the session (browser now, phone later).
# --------------------------------------------------------------------------- #
class AudioTransport(Protocol):
    """Raw audio both ways + a control/event channel to the UI. The session is
    transport-agnostic, so the SAME Live agent runs in the browser preview (P4-4, WS)
    and later on the phone (P4-6, Retell/SIP). Audio is PCM s16le: 16 kHz up (mic),
    24 kHz down (Live)."""

    async def start(self) -> None: ...
    async def send_audio(self, pcm: bytes) -> None: ...          # agent audio -> caller
    def recv_audio(self) -> AsyncIterator[bytes]: ...            # caller mic -> agent
    async def send_event(self, event: dict) -> None: ...         # transcript/disclosure/... -> UI
    async def cut_playback(self) -> None: ...                    # moderation/barge-in: silence NOW
    async def end(self) -> None: ...


# --------------------------------------------------------------------------- #
# 3. Streaming output moderation — the net (P4-3).
# --------------------------------------------------------------------------- #
class ModerationVerdict(str, Enum):
    ALLOW = "allow"    # keep speaking
    FLAG = "flag"      # log/emit but keep going (soft)
    BLOCK = "block"    # cut the current utterance + steer back


class StreamModerator(Protocol):
    """Screens Live's cumulative OUTPUT transcription as it forms. Called incrementally;
    returns fast (it runs inside the audio delay budget). Backed by the existing security
    screener (Model Armor). Reduces harm; never the sole guarantee."""

    async def check(self, cumulative_text: str) -> ModerationVerdict: ...


# --------------------------------------------------------------------------- #
# 4. Outcome + the session runtime (P4-2) — analogous to CallEngine, for Live.
# --------------------------------------------------------------------------- #
class LiveOutcome(str, Enum):
    BOOKED = "booked"
    QUALIFIED = "qualified"
    NOT_QUALIFIED = "not_qualified"
    OPTED_OUT = "opted_out"
    NO_ANSWER = "no_answer"
    FAILED = "failed"
    ENDED = "ended"


@dataclass
class LiveCallContext:
    """WHO the call is for — stamped on every event, used to resolve tenant-scoped tools
    (never chosen by the model)."""

    tenant_id: str
    agent_id: str
    campaign_id: Optional[str] = None
    lead_id: Optional[str] = None


class LiveAgentSession(Protocol):
    """Runs ONE conversation on Gemini Live:

      1. speak the scripted `disclosure_line` (code), THEN connect Live with the spec;
      2. stream mic audio -> Live, Live audio -> caller (24 kHz), honoring native VAD/barge-in;
      3. on a Live function-call, resolve the tenant's context + run the guarded
         `ToolHandler` (registry), return the result to Live;
      4. screen output transcription via the `StreamModerator`; on BLOCK, `cut_playback`
         and steer;
      5. emit events (transcript/disclosure/tool.invoked/guardrail.tripped/moderation.flagged/
         slot.booked/lead.outcome) to the sink;
      6. return the `LiveOutcome`.
    """

    async def run(
        self,
        spec: LiveAgentSpec,
        transport: AudioTransport,
        registry: ToolRegistry,
        moderator: StreamModerator,
        ctx: LiveCallContext,
    ) -> LiveOutcome: ...
