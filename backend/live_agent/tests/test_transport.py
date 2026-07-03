"""`PreviewAudioTransport` in isolation — proves the frozen `AudioTransport` contract
(`start`/`send_audio`/`recv_audio`/`send_event`/`cut_playback`/`end`) is met, and that
the router's push-in/drain-out queue (mirroring P3-4's `BrowserVoiceTransport`) behaves
correctly, without any WS/network."""

from __future__ import annotations

import asyncio

import pytest

from backend.live_agent.preview_transport import PreviewAudioTransport


class _Recorder:
    def __init__(self) -> None:
        self.json: list[dict] = []
        self.audio: list[bytes] = []

    async def send_json(self, data: dict) -> None:
        self.json.append(data)

    async def send_audio(self, data: bytes) -> None:
        self.audio.append(data)


def _transport():
    rec = _Recorder()
    return PreviewAudioTransport(rec.send_json, rec.send_audio), rec


@pytest.mark.anyio
async def test_send_audio_forwards_pcm_straight_through():
    transport, rec = _transport()
    await transport.send_audio(b"\x01\x02")
    assert rec.audio == [b"\x01\x02"]


@pytest.mark.anyio
async def test_send_event_forwards_the_dict_verbatim():
    transport, rec = _transport()
    await transport.send_event({"type": "tool", "name": "calendar", "timing": "in_call"})
    assert rec.json == [{"type": "tool", "name": "calendar", "timing": "in_call"}]


@pytest.mark.anyio
async def test_cut_playback_sends_a_dedicated_control_frame():
    transport, rec = _transport()
    await transport.cut_playback()
    assert rec.json == [{"type": "cut_playback"}]


@pytest.mark.anyio
async def test_push_audio_is_drained_in_order_by_recv_audio():
    transport, _rec = _transport()
    await transport.push_audio(b"one")
    await transport.push_audio(b"two")
    transport.push_stop()

    chunks = [c async for c in transport.recv_audio()]
    assert chunks == [b"one", b"two"]


@pytest.mark.anyio
async def test_push_stop_ends_the_recv_stream_with_nothing_buffered():
    transport, _rec = _transport()
    transport.push_stop()

    chunks = [c async for c in transport.recv_audio()]
    assert chunks == []


@pytest.mark.anyio
async def test_push_audio_after_stop_is_ignored():
    transport, _rec = _transport()
    transport.push_stop()
    await transport.push_audio(b"too late")

    chunks = [c async for c in transport.recv_audio()]
    assert chunks == []


@pytest.mark.anyio
async def test_start_and_end_are_inert_noops():
    transport, rec = _transport()
    await transport.start()
    await transport.end()
    assert rec.json == []
    assert rec.audio == []
