"""BrowserVoiceTransport over the ScriptedSpeechBridge — proves the CallTransport
contract (start/send_agent_utterance/receive/end) is met without any WS/network."""

from __future__ import annotations

import asyncio

import pytest

from backend.voice_preview.speech_bridge import ScriptedSpeechBridge
from backend.voice_preview.transport import BrowserVoiceTransport


class _Recorder:
    def __init__(self) -> None:
        self.json: list[dict] = []
        self.audio: list[bytes] = []

    async def send_json(self, data: dict) -> None:
        self.json.append(data)

    async def send_audio(self, data: bytes) -> None:
        self.audio.append(data)


def _transport(bridge=None):
    bridge = bridge or ScriptedSpeechBridge(tts_chunk_size=4)
    rec = _Recorder()
    return BrowserVoiceTransport(bridge, rec.send_json, rec.send_audio), rec, bridge


@pytest.mark.anyio
async def test_start_opens_the_bridge():
    transport, _rec, bridge = _transport()
    await transport.start(None)
    assert bridge.started


@pytest.mark.anyio
async def test_send_agent_utterance_emits_transcript_then_audio():
    transport, rec, _bridge = _transport()
    await transport.send_agent_utterance("hi there")

    assert rec.json == [{"type": "transcript", "role": "agent", "text": "hi there"}]
    assert b"".join(rec.audio) == b"hi there"


@pytest.mark.anyio
async def test_push_audio_finalizes_and_feeds_the_engine():
    transport, rec, _bridge = _transport()
    await transport.push_audio(b"Who is this?\n")

    assert {"type": "transcript", "role": "lead", "text": "Who is this?"} in rec.json

    utterance = await asyncio.wait_for(transport.receive().__anext__(), timeout=1)
    assert utterance.speaker == "lead"
    assert utterance.text == "Who is this?"


@pytest.mark.anyio
async def test_push_audio_buffers_partial_chunks_without_surfacing_anything():
    transport, rec, _bridge = _transport()
    await transport.push_audio(b"Who is ")

    assert rec.json == []


@pytest.mark.anyio
async def test_push_stop_ends_the_receive_stream():
    transport, _rec, _bridge = _transport()
    transport.push_stop()

    items = [utt async for utt in transport.receive()]
    assert items == []


@pytest.mark.anyio
async def test_push_audio_after_stop_is_ignored():
    transport, rec, _bridge = _transport()
    transport.push_stop()
    await transport.push_audio(b"too late\n")

    assert rec.json == []


@pytest.mark.anyio
async def test_end_closes_the_bridge():
    transport, _rec, bridge = _transport()
    await transport.end()
    assert bridge.closed
