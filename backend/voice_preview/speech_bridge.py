"""Speech bridge — audio <-> text at the `BrowserVoiceTransport` edge (P3-4).

`contracts/voice_preview` fixes the WIRE format (PCM in/out); it deliberately leaves
HOW audio becomes text (and back) to this package. `CallEngine` never sees audio — it
only ever drives text turns over `wrapper.complete()` — so this bridge's ONLY job is
translating at the edge: lead PCM -> lead text (STT) in `feed_audio`, agent text ->
agent PCM (TTS) in `synthesize`. It must never originate the agent's words itself
(that would let it bypass the code-emitted disclosure step): even if Gemini Live's
native audio-dialog mode is used for latency, this bridge only speaks text the engine
already decided, and only transcribes what the lead said. That is what keeps the
"reuse-the-engine" posture (`contracts/voice_preview` README) real rather than
aspirational.

`SpeechBridge` is the seam that lets `BrowserVoiceTransport` (and its tests) not care
whether STT/TTS is real: `ScriptedSpeechBridge` is a deterministic double (fake PCM is
just UTF-8 text) used in CI; `GeminiLiveSpeechBridge` is the real Gemini 3.1 Flash Live
adapter, exercised only by the documented live smoke test (see DONE.md) — CI never
imports `google.genai` (D8: provider SDKs never leak past their adapter, and stay
lazily imported so a key-less/SDK-less checkout still runs the whole test suite).
"""

from __future__ import annotations

import asyncio
import os
from typing import AsyncIterator, Optional, Protocol


class SpeechBridge(Protocol):
    """One call's audio<->text bridge, held by exactly one `BrowserVoiceTransport`."""

    async def start(self) -> None: ...

    async def feed_audio(self, chunk: bytes) -> Optional[str]:
        """Consume one inbound PCM chunk. Returns the finalized lead utterance once a
        turn boundary is detected, else None (still buffering)."""
        ...

    def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """Yield PCM chunks (agent voice) for one agent utterance."""
        ...

    async def close(self) -> None: ...


class ScriptedSpeechBridge:
    """CI test double. No codec, no network: fake PCM chunks ARE UTF-8 text, and a
    chunk ending in `b"\\n"` finalizes the buffered utterance (so a test can also
    exercise multi-chunk buffering by omitting the newline on earlier chunks).
    `synthesize` "speaks" by yielding the text's UTF-8 bytes in fixed-size pieces, so a
    test can assert audio frames went out without decoding real PCM."""

    def __init__(self, *, tts_chunk_size: int = 8) -> None:
        self.tts_chunk_size = tts_chunk_size
        self.started = False
        self.closed = False
        self._buf = b""

    async def start(self) -> None:
        self.started = True

    async def feed_audio(self, chunk: bytes) -> Optional[str]:
        self._buf += chunk
        if not self._buf.endswith(b"\n"):
            return None
        text = self._buf[:-1].decode("utf-8")
        self._buf = b""
        return text or None

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        data = text.encode("utf-8")
        for i in range(0, len(data), self.tts_chunk_size):
            yield data[i : i + self.tts_chunk_size]

    async def close(self) -> None:
        self.closed = True


class GeminiLiveSpeechBridge:
    """The real bridge, using the RIGHT Google product for each half:

      * STT (lead audio -> text): a Gemini Live session with `input_audio_transcription`.
        A background reader accumulates the transcription and enqueues a finalized
        utterance per turn (Live's own audio turn is ignored — it does NOT author the
        reply). Live is the audio-in transcriber here, nothing more.
      * TTS (agent text -> audio): the DEDICATED text-to-speech model, which reads the
        text verbatim. Live is conversational — asked to "speak" a line it would REPLY
        to it instead — so it is the wrong tool for output and is not used for TTS.

    The point of splitting it this way: the spoken reply is authored by the CallEngine
    over `ModelWrapper`, so the code-emitted AI disclosure and in-code tool guardrails
    are never bypassed (CLAUDE.md §5). The bridge only ears (STT) and mouth (TTS).

    Live-smoke seam (mirrors `RetellTransport`): CI drives `BrowserVoiceTransport`
    against `ScriptedSpeechBridge`; the `google.genai` SDK is imported lazily in
    `start()` so a key-less/SDK-less checkout never touches it (D8)."""

    def __init__(self, *, api_key: str, model: Optional[str] = None) -> None:
        self._api_key = api_key
        self._model = model or os.getenv(
            "GEMINI_MODEL_VOICE_LIVE", "gemini-3.1-flash-live-preview"
        )
        # TTS is a SEPARATE product from Live: Live is conversational (it would REPLY to
        # the agent's line, not read it), so the spoken output uses the dedicated
        # text-to-speech model, which reads text verbatim.
        self._tts_model = os.getenv("GEMINI_MODEL_TTS", "gemini-2.5-flash-preview-tts")
        self._voice = os.getenv("GEMINI_TTS_VOICE", "Kore")
        self._client = None
        self._stt_cm = None
        self._stt_session = None
        self._types = None
        # Finalized lead utterances, produced by the background reader and drained by
        # feed_audio. Decoupling reads from sends is the whole point (see below).
        self._utterances: "asyncio.Queue[str]" = asyncio.Queue()
        self._partial = ""
        self._reader: Optional[asyncio.Task] = None

    async def start(self) -> None:  # pragma: no cover - live leg, see DONE.md
        import google.genai as genai
        from google.genai import types

        self._types = types
        self._client = genai.Client(api_key=self._api_key)
        # The Live models are audio-native and REJECT a TEXT response modality (API
        # error 1007). For STT we ask for AUDIO + input transcription and read the
        # lead's `input_transcription`, ignoring the model's own audio turn — the
        # spoken REPLY is still authored by the CallEngine over ModelWrapper (so the
        # code-emitted disclosure + tools are never bypassed). See DONE.md.
        self._stt_cm = self._client.aio.live.connect(
            model=self._model,
            config=types.LiveConnectConfig(
                response_modalities=["AUDIO"],
                input_audio_transcription=types.AudioTranscriptionConfig(),
            ),
        )
        self._stt_session = await self._stt_cm.__aenter__()
        # CRITICAL: read the session in a BACKGROUND task, not inside feed_audio.
        # A Live `receive()` blocks until the model emits `turn_complete`, which only
        # happens after the lead stops speaking — but that requires their WHOLE
        # utterance to have been sent first. Reading inside feed_audio deadlocked:
        # the first tiny frame blocked the send loop, so no further audio ever reached
        # the model and turn_complete never fired (nothing was ever "heard"). The
        # reader accumulates input transcription and enqueues a finalized utterance on
        # each turn boundary; sending stays independent and non-blocking.
        self._reader = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:  # pragma: no cover - live leg
        try:
            async for response in self._stt_session.receive():
                sc = getattr(response, "server_content", None)
                if sc is None:
                    continue
                tr = getattr(sc, "input_transcription", None)
                if tr and tr.text:
                    self._partial += tr.text
                if getattr(sc, "turn_complete", False):
                    text = self._partial.strip()
                    self._partial = ""
                    if text:
                        self._utterances.put_nowait(text)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Session closed / errored — stop reading; close() tears the rest down.
            return

    async def feed_audio(self, chunk: bytes) -> Optional[str]:  # pragma: no cover
        types = self._types
        # Send only — never block on a read here (that was the deadlock).
        await self._stt_session.send_realtime_input(
            audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
        )
        # Surface a finalized utterance if the background reader produced one. Frames
        # stream continuously (incl. silence), so a queued utterance is drained within
        # a frame of the lead finishing their turn.
        try:
            return self._utterances.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:  # pragma: no cover
        """Read `text` aloud with the dedicated TTS model — NOT Live. Live is
        conversational and would answer the line instead of speaking it; the TTS model
        reads it verbatim, returning 24 kHz PCM. Non-streaming, so we synthesize the
        whole (short SDR) utterance then hand it out in frames for gapless playback."""
        types = self._types
        response = await self._client.aio.models.generate_content(
            model=self._tts_model,
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=self._voice
                        )
                    )
                ),
            ),
        )
        data = response.candidates[0].content.parts[0].inline_data.data
        frame = 4096
        for i in range(0, len(data), frame):
            yield data[i : i + frame]

    async def close(self) -> None:  # pragma: no cover
        if self._reader is not None:
            self._reader.cancel()
            try:
                await self._reader
            except (asyncio.CancelledError, Exception):
                pass
        if self._stt_cm is not None:
            try:
                await self._stt_cm.__aexit__(None, None, None)
            except Exception:
                pass


def build_speech_bridge() -> SpeechBridge:
    """Env-gated mock<->real switch (same posture as `providers.py` / the Retell
    transport factory): Gemini Live once a key is present, else the scripted double —
    so a key-less checkout still boots and a component test can drive the real wire
    protocol end-to-end without network."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if api_key:
        return GeminiLiveSpeechBridge(api_key=api_key)
    return ScriptedSpeechBridge()
