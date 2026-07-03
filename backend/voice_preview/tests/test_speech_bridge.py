"""ScriptedSpeechBridge (the CI double) + the env-gated build_speech_bridge switch."""

from __future__ import annotations

import pytest

from backend.voice_preview.speech_bridge import (
    GeminiLiveSpeechBridge,
    ScriptedSpeechBridge,
    build_speech_bridge,
)


@pytest.mark.anyio
async def test_scripted_bridge_finalizes_on_newline():
    bridge = ScriptedSpeechBridge()
    await bridge.start()
    assert bridge.started

    assert await bridge.feed_audio(b"Hello?\n") == "Hello?"


@pytest.mark.anyio
async def test_scripted_bridge_buffers_across_chunks_until_newline():
    bridge = ScriptedSpeechBridge()
    await bridge.start()

    assert await bridge.feed_audio(b"Who is ") is None
    assert await bridge.feed_audio(b"this?\n") == "Who is this?"


@pytest.mark.anyio
async def test_scripted_bridge_synthesize_chunks_utf8_bytes():
    bridge = ScriptedSpeechBridge(tts_chunk_size=4)
    chunks = [c async for c in bridge.synthesize("hello world")]
    assert len(chunks) > 1
    assert b"".join(chunks) == b"hello world"


@pytest.mark.anyio
async def test_scripted_bridge_close_marks_closed():
    bridge = ScriptedSpeechBridge()
    await bridge.close()
    assert bridge.closed


def test_build_speech_bridge_defaults_to_scripted_without_a_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert isinstance(build_speech_bridge(), ScriptedSpeechBridge)


def test_build_speech_bridge_selects_gemini_live_once_keyed(monkeypatch):
    # Constructing the bridge must NOT import google.genai (D8: lazy, only in
    # start()) — this assertion would fail at import time if it did, since the SDK
    # need not be installed for this test to run.
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    bridge = build_speech_bridge()
    assert isinstance(bridge, GeminiLiveSpeechBridge)
