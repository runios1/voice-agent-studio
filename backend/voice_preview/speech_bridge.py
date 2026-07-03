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
    """The real bridge: Gemini 3.1 Flash Live for streaming STT (lead audio -> text)
    and TTS (agent text -> audio). Two separate Live sessions on purpose — STT must
    NOT let the model also generate a conversational reply (that's the engine's job
    over `ModelWrapper`; letting Live's own turn also "answer" would double-speak and
    is exactly the drift the wire contract forbids), so the STT session pins
    `response_modalities=["TEXT"]` with `input_audio_transcription` and never sends
    the transcript back as a prompt; the TTS session is a one-shot `AUDIO` turn per
    agent utterance.

    This is the documented live-smoke-test seam (mirrors `RetellTransport`): CI drives
    `BrowserVoiceTransport` against `ScriptedSpeechBridge` only. `start()` is where the
    `google.genai` SDK is imported — lazily, so a key-less/SDK-less checkout never
    touches it (D8)."""

    def __init__(self, *, api_key: str, model: Optional[str] = None) -> None:
        self._api_key = api_key
        self._model = model or os.getenv("GEMINI_MODEL_VOICE_LIVE", "gemini-3.1-flash-live")
        self._client = None
        self._stt_cm = None
        self._stt_session = None

    async def start(self) -> None:  # pragma: no cover - live leg, see DONE.md
        import google.genai as genai
        from google.genai import types

        self._types = types
        self._client = genai.Client(api_key=self._api_key)
        self._stt_cm = self._client.aio.live.connect(
            model=self._model,
            config=types.LiveConnectConfig(
                response_modalities=["TEXT"],
                input_audio_transcription=types.AudioTranscriptionConfig(),
            ),
        )
        self._stt_session = await self._stt_cm.__aenter__()

    async def feed_audio(self, chunk: bytes) -> Optional[str]:  # pragma: no cover
        types = self._types
        await self._stt_session.send_realtime_input(
            audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
        )
        # Drain whatever Gemini has ready for this push. A production hardening step
        # (documented, not done here — see DONE.md) is a dedicated background reader
        # task decoupled from `feed_audio`, so a slow transcription doesn't stall the
        # next inbound chunk; correctness (never losing/reordering text) holds either
        # way because the queue this feeds is FIFO.
        text: Optional[str] = None
        async for response in self._stt_session.receive():
            transcription = getattr(response.server_content, "input_transcription", None)
            if transcription and transcription.text:
                text = (text or "") + transcription.text
            if getattr(response.server_content, "turn_complete", False):
                break
        return text

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:  # pragma: no cover
        types = self._types
        async with self._client.aio.live.connect(
            model=self._model,
            config=types.LiveConnectConfig(response_modalities=["AUDIO"]),
        ) as session:
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=text)]),
                turn_complete=True,
            )
            async for response in session.receive():
                model_turn = getattr(response.server_content, "model_turn", None)
                if not model_turn:
                    continue
                for part in model_turn.parts:
                    data = getattr(getattr(part, "inline_data", None), "data", None)
                    if data:
                        yield data

    async def close(self) -> None:  # pragma: no cover
        if self._stt_cm is not None:
            await self._stt_cm.__aexit__(None, None, None)


def build_speech_bridge() -> SpeechBridge:
    """Env-gated mock<->real switch (same posture as `providers.py` / the Retell
    transport factory): Gemini Live once a key is present, else the scripted double —
    so a key-less checkout still boots and a component test can drive the real wire
    protocol end-to-end without network."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if api_key:
        return GeminiLiveSpeechBridge(api_key=api_key)
    return ScriptedSpeechBridge()
