"""The compliance speaker — reads fixed text aloud WITHOUT ever going through Live.

Live is conversational: asked to "say this line," it would reply to it rather than
read it verbatim (the same reason `backend/voice_preview/speech_bridge.py` keeps TTS
off Live). Two lines in the Live-native turn loop are compliance-critical fixed text
that must never be paraphrased or dropped by a model: the scripted `disclosure_line`
(spoken before Live even connects) and the DNC opt-out acknowledgement (spoken by
cutting Live off mid-call, D-security §5). Both go through this dedicated,
non-conversational speaker.
"""

from __future__ import annotations

import os
from typing import AsyncIterator, Optional, Protocol


class Speaker(Protocol):
    """Turns fixed text into PCM audio, verbatim. Never reasons about the text."""

    def speak(self, text: str) -> AsyncIterator[bytes]: ...


class ScriptedSpeaker:
    """CI test double (mirrors `ScriptedSpeechBridge`): no codec, no network — fake
    PCM chunks are just the text's UTF-8 bytes, so a test can assert on what was
    "spoken" without decoding real audio."""

    def __init__(self, *, chunk_size: int = 8) -> None:
        self.chunk_size = chunk_size
        self.spoken: list[str] = []

    async def speak(self, text: str) -> AsyncIterator[bytes]:
        self.spoken.append(text)
        data = text.encode("utf-8")
        for i in range(0, len(data), self.chunk_size):
            yield data[i : i + self.chunk_size]


class GeminiTtsSpeaker:
    """The real speaker: the dedicated Gemini text-to-speech model (NOT Live),
    returning 24 kHz PCM — same product choice and rationale as
    `GeminiLiveSpeechBridge.synthesize`."""

    def __init__(
        self, *, api_key: str, model: Optional[str] = None, voice: Optional[str] = None
    ) -> None:
        self._api_key = api_key
        self._model = model or os.getenv("GEMINI_MODEL_TTS", "gemini-2.5-flash-preview-tts")
        self._voice = voice or os.getenv("GEMINI_TTS_VOICE", "Kore")
        self._client = None

    async def speak(self, text: str) -> AsyncIterator[bytes]:  # pragma: no cover - live smoke
        import google.genai as genai
        from google.genai import types

        if self._client is None:
            self._client = genai.Client(api_key=self._api_key)
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self._voice)
                    )
                ),
            ),
        )
        data = response.candidates[0].content.parts[0].inline_data.data
        frame = 4096
        for i in range(0, len(data), frame):
            yield data[i : i + frame]


def default_speaker() -> Speaker:
    """Env-gated mock<->real switch (same posture as `build_speech_bridge`): real TTS
    once a key is present, else the scripted double — a key-less checkout still boots."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if api_key:
        return GeminiTtsSpeaker(api_key=api_key)
    return ScriptedSpeaker()
