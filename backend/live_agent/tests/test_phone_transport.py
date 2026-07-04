"""PhoneAudioTransport driven against a fake Twilio media socket + fake call placer —
no network, no Twilio, no real call."""

from __future__ import annotations

import asyncio
import base64
import json

import pytest
from fastapi import WebSocketDisconnect

from backend.live_agent.phone_transport import (
    PhoneAudioTransport,
    PhoneNotAnswered,
)
from backend.live_agent.telephony_codec import pcm16_to_ulaw


class FakePlacer:
    def __init__(self) -> None:
        self.placed: list[dict] = []
        self.hung: list[str] = []

    async def place(self, *, to: str, from_: str, twiml: str) -> str:
        self.placed.append({"to": to, "from": from_, "twiml": twiml})
        return "CA-test"

    async def hangup(self, call_sid: str) -> None:
        self.hung.append(call_sid)


class FakeTwilioWS:
    """Yields scripted inbound Twilio JSON frames; records what we send back."""

    def __init__(self, inbound: list[dict]) -> None:
        self._inbound = list(inbound)
        self.sent: list[dict] = []
        self.closed = False

    async def receive_text(self) -> str:
        if self._inbound:
            return json.dumps(self._inbound.pop(0))
        raise WebSocketDisconnect(1000)  # stream exhausted -> serve loop ends

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def close(self, code: int = 1000) -> None:
        self.closed = True


def _transport(placer, **kw) -> PhoneAudioTransport:
    return PhoneAudioTransport(
        to_number="+15551230000",
        from_number="+18312530740",
        public_wss_base="wss://example.ngrok-free.app",
        placer=placer,
        **kw,
    )


async def test_places_call_with_connect_stream_twiml_to_the_token_url():
    placer = FakePlacer()
    t = _transport(placer)
    ws = FakeTwilioWS([{"event": "start", "start": {"streamSid": "MZ1", "callSid": "CA1"}}])

    serve = asyncio.create_task(t.serve(ws))
    await t.start()
    await serve

    twiml = placer.placed[0]["twiml"]
    assert "<Connect><Stream" in twiml
    assert f"wss://example.ngrok-free.app/twilio/media/{t._token}" in twiml
    assert placer.placed[0]["to"] == "+15551230000"


async def test_inbound_media_is_decoded_to_live_pcm_and_send_audio_frames_out():
    placer = FakePlacer()
    t = _transport(placer)
    ulaw_frame = pcm16_to_ulaw(b"\x10\x10" * 160)  # 20 ms of 8 kHz μ-law
    ws = FakeTwilioWS(
        [
            {"event": "start", "start": {"streamSid": "MZ1", "callSid": "CA1"}},
            {"event": "media", "media": {"payload": base64.b64encode(ulaw_frame).decode()}},
            {"event": "stop"},
        ]
    )

    serve = asyncio.create_task(t.serve(ws))
    await t.start()

    # caller audio -> agent: one decoded 16 kHz PCM frame, then the stream ends
    frames = [f async for f in t.recv_audio()]
    assert len(frames) == 1
    assert len(frames[0]) == 640  # 20 ms μ-law (160B) -> 8k pcm -> 16k pcm = 320 samples

    # agent audio -> caller: a Twilio `media` frame with base64 μ-law
    await t.send_audio(b"\x20\x20" * 720)  # 24 kHz PCM
    media = [m for m in ws.sent if m.get("event") == "media"]
    assert media and media[0]["streamSid"] == "MZ1"
    assert base64.b64decode(media[0]["media"]["payload"])  # valid μ-law bytes

    # barge-in -> Twilio `clear`
    await t.cut_playback()
    assert any(m.get("event") == "clear" and m["streamSid"] == "MZ1" for m in ws.sent)

    await t.end()
    assert placer.hung == ["CA-test"]
    await serve


async def test_no_answer_times_out_as_PhoneNotAnswered():
    placer = FakePlacer()
    t = _transport(placer, connect_timeout=0.05)  # Twilio never connects the stream
    with pytest.raises(PhoneNotAnswered):
        await t.start()


def test_public_wss_base_prefers_explicit_then_derives_from_render(monkeypatch):
    from backend.live_agent import phone_transport as pt

    monkeypatch.delenv("PUBLIC_WSS_BASE", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_HOSTNAME", raising=False)
    assert pt.public_wss_base() is None

    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", "myapp.onrender.com")
    assert pt.public_wss_base() == "wss://myapp.onrender.com"  # derived on Render

    monkeypatch.setenv("PUBLIC_WSS_BASE", "wss://explicit.example/")
    assert pt.public_wss_base() == "wss://explicit.example"  # explicit wins, slash trimmed
