"""The WS route end-to-end, via FastAPI TestClient — no real socket/network.

Proves the contract's non-negotiable design intent: the preview reuses the exact same
`CallEngine` turn loop as a real call, so disclosure-first, in-call tools, and the
event trail carry through to the wire protocol's frames.

Frame ordering asserted here follows `BrowserVoiceTransport.send_agent_utterance`:
a JSON `transcript` frame, THEN the utterance's audio bytes (as many binary frames as
`ScriptedSpeechBridge`'s chunk size yields) — never interleaved with another JSON
frame until the next lifecycle point.
"""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from contracts.config_schema.schema import AgentConfig
from contracts.events.schema import EventType

from backend.config_gate.api import current_user
from backend.voice_preview.router import create_router
from backend.voice_preview.speech_bridge import ScriptedSpeechBridge
from backend.voice_runtime.events import CollectingEventSink
from backend.voice_runtime.fixtures import config_with_calendar
from backend.voice_runtime.mocks import MockBookMeetingHandler, MockToolRegistry, ScriptedToolWrapper, tool_call
from backend.runtime_loop.fixtures import sample_ready_config

TENANT = "tenant-1"


class _FakeConfigSource:
    def __init__(self, config: AgentConfig | None) -> None:
        self._config = config

    def get_config(self, agent_id: str, tenant_id: str):
        if self._config is None or tenant_id != TENANT:
            return None
        return self._config


class _FakeRegistryBuilder:
    def __init__(self, registry) -> None:
        self._registry = registry

    def registry_for(self, config, sink):
        return self._registry


def _build_app(config, model, *, registry=None, sink=None):
    app = FastAPI()
    sink = sink or CollectingEventSink()
    router = create_router(
        _FakeConfigSource(config),
        _FakeRegistryBuilder(registry or MockToolRegistry()),
        model,
        sink,
        speech_bridge_factory=lambda: ScriptedSpeechBridge(tts_chunk_size=4),
    )
    app.include_router(router)
    app.dependency_overrides[current_user] = lambda: TENANT
    return app


def _recv_json(ws) -> dict:
    msg = ws.receive()
    assert msg.get("text") is not None, f"expected a JSON frame, got: {msg}"
    return json.loads(msg["text"])


def _recv_agent_transcript_with_audio(ws) -> tuple[dict, bytes]:
    """An agent utterance: the transcript frame, then its synthesized audio (as many
    binary frames as the bridge's chunk size yields, totaling the text's byte length)."""
    transcript = _recv_json(ws)
    assert transcript["type"] == "transcript"
    assert transcript["role"] == "agent"
    expected_len = len(transcript["text"].encode("utf-8"))
    audio = b""
    while len(audio) < expected_len:
        msg = ws.receive()
        assert msg.get("bytes") is not None, f"expected audio, got: {msg}"
        audio += msg["bytes"]
    return transcript, audio


def test_disclosure_first_then_transcript_audio_and_clean_hangup():
    config = sample_ready_config(agent_id="agent-1")
    model = ScriptedToolWrapper(["Hi, I'm calling about Acme.", "Thanks, bye."])
    app = _build_app(config, model)
    client = TestClient(app)

    with client.websocket_connect("/agents/agent-1/preview/voice") as ws:
        ws.send_json({"type": "start"})

        # Disclosure badges BEFORE the opening line is spoken.
        disclosure = _recv_json(ws)
        assert disclosure == {"type": "disclosure"}

        transcript, audio = _recv_agent_transcript_with_audio(ws)
        script = config.conversation.disclosure.disclosure_script
        assert transcript["text"].startswith(script)
        assert "Acme" in transcript["text"]
        # The audio actually carries the same text the transcript claims (proves the
        # STT/TTS bridge, not just the JSON side channel).
        assert audio.decode("utf-8") == transcript["text"]

        ws.send_json({"type": "stop"})

        outcome = _recv_json(ws)
        assert outcome["type"] == "outcome"

        ended = _recv_json(ws)
        assert ended == {"type": "ended", "outcome": outcome["outcome"]}


def test_lead_speech_round_trips_and_tool_call_books_a_slot():
    config = config_with_calendar(agent_id="agent-2")
    model = ScriptedToolWrapper(
        [
            "Hi, calling about Acme.",
            tool_call("calendar", start_iso="2026-07-06T10:00:00"),
            "Booked you in.",
        ]
    )
    registry = MockToolRegistry(MockBookMeetingHandler())
    sink = CollectingEventSink()
    app = _build_app(config, model, registry=registry, sink=sink)
    client = TestClient(app)

    with client.websocket_connect("/agents/agent-2/preview/voice") as ws:
        ws.send_json({"type": "start"})
        _recv_json(ws)  # disclosure
        _recv_agent_transcript_with_audio(ws)  # opening

        ws.send_bytes(b"Sure, book Monday 10am.\n")
        lead_transcript = _recv_json(ws)
        assert lead_transcript == {
            "type": "transcript",
            "role": "lead",
            "text": "Sure, book Monday 10am.",
        }

        agent_transcript, _audio = _recv_agent_transcript_with_audio(ws)
        assert agent_transcript["text"] == "Booked you in."

        ws.send_json({"type": "stop"})
        outcome = _recv_json(ws)
        assert outcome == {"type": "outcome", "outcome": "booked"}
        ended = _recv_json(ws)
        assert ended == {"type": "ended", "outcome": "booked"}

    # The shared compliance sink got everything too, not just the WS frames.
    types = [e.type for e in sink.events]
    assert EventType.CALL_STARTED in types
    assert EventType.SLOT_BOOKED in types
    assert EventType.CALL_ENDED in types


def test_unknown_agent_gets_an_error_frame_not_a_stack_trace():
    app = _build_app(None, ScriptedToolWrapper("hi"))
    client = TestClient(app)

    with client.websocket_connect("/agents/nope/preview/voice") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
