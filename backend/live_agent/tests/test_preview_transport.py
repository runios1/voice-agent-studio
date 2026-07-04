"""The Live-native preview WS route end-to-end, via FastAPI TestClient — no real
socket/network, and no real Live/compiler/moderator (P4-1/2/3 aren't merged yet;
this workstream mocks them behind the frozen `contracts/live_agent` Protocols, per
the dispatch boundary).

Proves: a `start` opens the call and runs the injected `LiveAgentSession`; whatever
the session sends via `AudioTransport.send_event` (disclosure/transcript/tool/
moderation) reaches the wire verbatim; `cut_playback()` is a dedicated frame,
independent of any `moderation` display event; inbound binary frames reach the
session through `recv_audio`; an unknown agent and a session crash both end in a
calm `error` frame, never a stack trace; and the final `ended` frame carries the
`LiveOutcome` the session returned.
"""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from contracts.config_schema.schema import AgentConfig
from contracts.live_agent.interface import (
    AudioTransport,
    LiveAgentSpec,
    LiveCallContext,
    LiveOutcome,
    ModerationVerdict,
)
from contracts.tool_registry.interface import ToolRegistry

from backend.live_agent.preview_transport import create_router
from backend.voice_runtime.events import CollectingEventSink
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
    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self._registry = registry

    def registry_for(self, config, sink):
        return self._registry


class _FakeCompiler:
    """`LiveAgentCompiler` double — no network, just records the config it saw."""

    def __init__(self) -> None:
        self.compiled_configs: list[AgentConfig] = []

    def compile(self, config: AgentConfig) -> LiveAgentSpec:
        self.compiled_configs.append(config)
        return LiveAgentSpec(
            system_instruction="be a good SDR",
            disclosure_line="Hi, this is an AI assistant calling.",
            tool_declarations=[],
        )


class _FakeModerator:
    async def check(self, cumulative_text: str) -> ModerationVerdict:
        return ModerationVerdict.ALLOW


class _ScriptedSession:
    """`LiveAgentSession` double. `actions` is a list of callables invoked in order,
    each given the live `AudioTransport` so it can `send_event`/`send_audio`/
    `cut_playback`; `recv_audio` is drained into `received_audio` concurrently so a
    test can also assert inbound audio reached the session. Returns `outcome` (or
    raises `to_raise`) once the actions + drain finish."""

    def __init__(
        self,
        actions: list,
        *,
        outcome: LiveOutcome | None = LiveOutcome.ENDED,
        to_raise: Exception | None = None,
        drain_audio: bool = True,
    ) -> None:
        self._actions = actions
        self._outcome = outcome
        self._to_raise = to_raise
        self._drain_audio = drain_audio
        self.received_audio: list[bytes] = []
        self.ctx: LiveCallContext | None = None
        self.spec: LiveAgentSpec | None = None

    async def run(self, spec, transport: AudioTransport, registry, moderator, ctx) -> LiveOutcome:
        self.spec = spec
        self.ctx = ctx
        for action in self._actions:
            await action(transport)
        if self._drain_audio:
            async for chunk in transport.recv_audio():
                self.received_audio.append(chunk)
        if self._to_raise is not None:
            raise self._to_raise
        return self._outcome


def _build_app(config, *, session: _ScriptedSession, compiler=None, registry=None, sink=None):
    app = FastAPI()
    router = create_router(
        _FakeConfigSource(config),
        _FakeRegistryBuilder(registry),
        compiler or _FakeCompiler(),
        sink or CollectingEventSink(),
        session_factory=lambda _sink: session,
        moderator_factory=_FakeModerator,
    )
    app.include_router(router)
    from backend.config_gate.api import current_user

    app.dependency_overrides[current_user] = lambda: TENANT
    return app


def _recv_json(ws) -> dict:
    msg = ws.receive()
    assert msg.get("text") is not None, f"expected a JSON frame, got: {msg}"
    return json.loads(msg["text"])


def test_session_events_reach_the_wire_verbatim_then_ended_with_outcome():
    async def speak_disclosure(transport):
        await transport.send_event({"type": "disclosure"})

    async def speak_opening(transport):
        await transport.send_event(
            {"type": "transcript", "role": "agent", "text": "Hi, calling about Acme."}
        )
        await transport.send_audio(b"\x00\x01" * 4)

    async def invoke_tool(transport):
        await transport.send_event({"type": "tool", "name": "calendar", "timing": "in_call"})

    async def flag_then_block(transport):
        await transport.send_event({"type": "moderation", "verdict": "flag"})
        await transport.send_event({"type": "moderation", "verdict": "block"})

    session = _ScriptedSession(
        [speak_disclosure, speak_opening, invoke_tool, flag_then_block],
        outcome=LiveOutcome.BOOKED,
    )
    app = _build_app(sample_ready_config(agent_id="agent-1"), session=session)
    client = TestClient(app)

    with client.websocket_connect("/agents/agent-1/preview/voice") as ws:
        ws.send_json({"type": "start"})

        assert _recv_json(ws) == {"type": "disclosure"}
        assert _recv_json(ws) == {
            "type": "transcript",
            "role": "agent",
            "text": "Hi, calling about Acme.",
        }
        audio = ws.receive()
        assert audio.get("bytes") == b"\x00\x01" * 4
        assert _recv_json(ws) == {"type": "tool", "name": "calendar", "timing": "in_call"}
        assert _recv_json(ws) == {"type": "moderation", "verdict": "flag"}
        assert _recv_json(ws) == {"type": "moderation", "verdict": "block"}

        ws.send_json({"type": "stop"})

        assert _recv_json(ws) == {"type": "ended", "outcome": "booked"}

    # the compiler saw the caller's own built config, and the session got a
    # preview-scoped context (never the model's own choice of tenant).
    assert session.ctx.tenant_id == TENANT
    assert session.ctx.agent_id == "agent-1"


def test_cut_playback_is_a_dedicated_frame_independent_of_moderation_events():
    async def cut(transport):
        await transport.cut_playback()

    session = _ScriptedSession([cut])
    app = _build_app(sample_ready_config(agent_id="agent-1"), session=session)
    client = TestClient(app)

    with client.websocket_connect("/agents/agent-1/preview/voice") as ws:
        ws.send_json({"type": "start"})
        assert _recv_json(ws) == {"type": "cut_playback"}
        ws.send_json({"type": "stop"})
        assert _recv_json(ws) == {"type": "ended", "outcome": "ended"}


def test_inbound_audio_reaches_the_session_via_recv_audio():
    session = _ScriptedSession([])
    app = _build_app(sample_ready_config(agent_id="agent-1"), session=session)
    client = TestClient(app)

    with client.websocket_connect("/agents/agent-1/preview/voice") as ws:
        ws.send_json({"type": "start"})
        ws.send_bytes(b"chunk-one")
        ws.send_bytes(b"chunk-two")
        ws.send_json({"type": "stop"})
        assert _recv_json(ws) == {"type": "ended", "outcome": "ended"}

    assert session.received_audio == [b"chunk-one", b"chunk-two"]


def test_unknown_agent_gets_an_error_frame_not_a_stack_trace():
    app = _build_app(None, session=_ScriptedSession([]))
    client = TestClient(app)

    with client.websocket_connect("/agents/nope/preview/voice") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"


def test_a_session_crash_yields_a_calm_error_then_ended_not_a_stack_trace():
    session = _ScriptedSession([], to_raise=RuntimeError("live socket blew up"))
    app = _build_app(sample_ready_config(agent_id="agent-1"), session=session)
    client = TestClient(app)

    with client.websocket_connect("/agents/agent-1/preview/voice") as ws:
        ws.send_json({"type": "start"})
        ws.send_json({"type": "stop"})
        assert _recv_json(ws) == {
            "type": "error",
            "message": "The call hit a problem and ended.",
        }
        assert _recv_json(ws) == {"type": "ended"}


def test_missing_start_message_is_a_clean_error():
    app = _build_app(sample_ready_config(agent_id="agent-1"), session=_ScriptedSession([]))
    client = TestClient(app)

    with client.websocket_connect("/agents/agent-1/preview/voice") as ws:
        ws.send_json({"type": "not-a-start"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
