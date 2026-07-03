"""Transports — the reference text transport + the Retell bridge."""

from __future__ import annotations

import asyncio

import pytest

from contracts.voice_runtime.interface import CallOutcome

from backend.voice_runtime.transports import (
    MockVoiceTransport,
    RetellTransport,
    TextTransport,
    _call_id_from_path,
)


@pytest.mark.anyio
async def test_text_transport_yields_lead_lines_then_closes():
    t = TextTransport(["one", "two"])
    await t.start("+15550000000")
    assert t.started and t.phone == "+15550000000"

    seen = []
    async for utt in t.receive():
        seen.append(utt.text)
    assert seen == ["one", "two"]

    await t.send_agent_utterance("hello")
    await t.end()
    assert t.agent_lines == ["hello"] and t.ended


@pytest.mark.anyio
async def test_mock_voice_forced_outcome_yields_no_turns():
    t = MockVoiceTransport(["ignored"], forced_outcome=CallOutcome.VOICEMAIL)
    await t.start(None)
    seen = [u async for u in t.receive()]
    assert seen == []  # forced pre-conversation outcome => no conversation
    assert t.forced_outcome == CallOutcome.VOICEMAIL


@pytest.mark.anyio
async def test_retell_transport_is_a_guarded_seam():
    t = RetellTransport()  # no api key
    with pytest.raises(RuntimeError, match="not wired for CI"):
        await t.start("+15551112222")


@pytest.mark.anyio
async def test_retell_transport_needs_agent_number():
    t = RetellTransport(api_key="k")  # no from-number
    with pytest.raises(RuntimeError, match="agent_number"):
        await t.start("+15551112222")


def test_call_id_from_path():
    assert _call_id_from_path("/llm-websocket/abc123") == "abc123"
    assert _call_id_from_path("/llm-websocket/abc123/") == "abc123"
    assert _call_id_from_path("") is None


class _FakeRetellConnection:
    """Stands in for the websocket Retell dials back with — captures every frame
    the transport sends so the bridging logic can be asserted without a real
    socket, the SDK, or network access."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, data: str) -> None:
        import json

        self.sent.append(json.loads(data))


@pytest.mark.anyio
async def test_retell_transport_bridges_response_required_to_utterance():
    t = RetellTransport(api_key="k", agent_number="+15550000000")
    t._connection = _FakeRetellConnection()

    await t._on_message(
        {
            "interaction_type": "response_required",
            "response_id": 1,
            "transcript": [{"role": "user", "content": "hello there"}],
        }
    )

    utt = await asyncio.wait_for(t._incoming.get(), timeout=1)
    assert utt.speaker == "lead" and utt.text == "hello there"
    assert t._response_id == 1
    assert t._response_ready.is_set()


@pytest.mark.anyio
async def test_retell_transport_opening_response_required_has_no_lead_turn():
    # The first response_required (empty transcript) primes send_agent_utterance's
    # opening line; it must NOT synthesize a lead Utterance.
    t = RetellTransport(api_key="k", agent_number="+15550000000")
    t._connection = _FakeRetellConnection()

    await t._on_message({"interaction_type": "response_required", "response_id": 0, "transcript": []})

    assert t._incoming.empty()
    assert t._response_ready.is_set()


@pytest.mark.anyio
async def test_retell_transport_reminder_with_no_new_turn_is_not_a_lead_utterance():
    t = RetellTransport(api_key="k", agent_number="+15550000000")
    t._connection = _FakeRetellConnection()

    await t._on_message(
        {
            "interaction_type": "reminder_required",
            "response_id": 2,
            "transcript": [{"role": "agent", "content": "still there?"}],
        }
    )

    assert t._incoming.empty()
    assert t._response_id == 2


@pytest.mark.anyio
async def test_retell_transport_answers_ping_pong():
    t = RetellTransport(api_key="k", agent_number="+15550000000")
    conn = _FakeRetellConnection()
    t._connection = conn

    await t._on_message({"interaction_type": "ping_pong", "timestamp": 42})

    assert conn.sent == [{"response_type": "ping_pong", "timestamp": 42}]


@pytest.mark.anyio
async def test_retell_transport_send_agent_utterance_answers_pending_response():
    t = RetellTransport(api_key="k", agent_number="+15550000000")
    conn = _FakeRetellConnection()
    t._connection = conn
    t._response_id = 3
    t._response_ready.set()

    await t.send_agent_utterance("hi there")

    assert conn.sent == [
        {
            "response_type": "response",
            "response_id": 3,
            "content": "hi there",
            "content_complete": True,
        }
    ]
    assert not t._response_ready.is_set()


@pytest.mark.anyio
async def test_retell_transport_transfer_requires_configured_number():
    t = RetellTransport(api_key="k", agent_number="+15550000000")
    t._connection = _FakeRetellConnection()

    with pytest.raises(RuntimeError, match="transfer_number"):
        await t.transfer("lead asked for a human")


@pytest.mark.anyio
async def test_retell_transport_transfer_sends_transfer_number():
    t = RetellTransport(
        api_key="k", agent_number="+15550000000", transfer_number="+15559998888"
    )
    conn = _FakeRetellConnection()
    t._connection = conn
    t._response_id = 4

    await t.transfer("lead asked for a human")

    assert conn.sent == [
        {
            "response_type": "response",
            "response_id": 4,
            "content": "",
            "content_complete": True,
            "transfer_number": "+15559998888",
        }
    ]


@pytest.mark.anyio
async def test_retell_transport_end_sends_end_call_and_closes_stream():
    t = RetellTransport(api_key="k", agent_number="+15550000000")
    conn = _FakeRetellConnection()
    t._connection = conn
    t._response_id = 5

    await t.end()

    assert conn.sent == [
        {
            "response_type": "response",
            "response_id": 5,
            "content": "",
            "content_complete": True,
            "end_call": True,
        }
    ]
    item = await asyncio.wait_for(t._incoming.get(), timeout=1)
    assert item is None
