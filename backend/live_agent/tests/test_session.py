"""P4-2 — `GeminiLiveAgentSession` behavior, driven entirely against fakes: a scripted
`LiveConnection`, a fake transport/registry/moderator. No network, no `google.genai`
import. See DONE.md for what's smoke-only."""

from __future__ import annotations

import asyncio

from contracts.events.schema import EventType
from contracts.live_agent.interface import (
    LiveAgentSpec,
    LiveCallContext,
    LiveOutcome,
    ModerationVerdict,
)

from backend.live_agent.events import CollectingEventSink
from backend.live_agent.live_connection import LiveEvent
from backend.live_agent.session import GeminiLiveAgentSession, OPT_OUT_ACK
from backend.live_agent.speaker import ScriptedSpeaker
from backend.live_agent.tests.fakes import (
    FakeAudioTransport,
    FakeHandler,
    FakeLiveConnector,
    FakeToolRegistry,
    ScriptedModerator,
    function_call,
)

CTX = LiveCallContext(tenant_id="t1", agent_id="a1", campaign_id="c1", lead_id="l1")


def _spec(**overrides) -> LiveAgentSpec:
    return LiveAgentSpec(
        system_instruction="You are a helpful SDR.",
        disclosure_line="This call may use an AI assistant.",
        tool_declarations=[],
        moderation_buffer_ms=0,
        **overrides,
    )


def _session(connector, moderator=None):
    return (
        GeminiLiveAgentSession(
            CollectingEventSink(),
            live_connector=connector,
            speaker=ScriptedSpeaker(chunk_size=1024),
        ),
        moderator or ScriptedModerator(),
    )


async def test_disclosure_is_spoken_before_live_connects():
    connector = FakeLiveConnector([LiveEvent(turn_complete=True)])
    session, moderator = _session(connector)
    speaker = session._speaker  # ScriptedSpeaker double
    transport = FakeAudioTransport()
    registry = FakeToolRegistry({})

    outcome = await session.run(_spec(), transport, registry, moderator, CTX)

    assert speaker.spoken == ["This call may use an AI assistant."]
    assert connector.entered  # Live wasn't connected until after speak() awaited
    assert transport.events[0] == {"type": "disclosure", "text": "This call may use an AI assistant."}
    assert outcome == LiveOutcome.NO_ANSWER  # no lead speech at all in this script


async def test_disclosure_event_emitted_before_live_connects_in_order():
    """The disclosure Speaker call happens strictly before the live_connector call —
    proven by ordering a side-effecting connector after a synchronous speak()."""
    order: list[str] = []

    class RecordingConnector(FakeLiveConnector):
        async def __aenter__(self):
            order.append("connect")
            return await super().__aenter__()

    class RecordingSpeaker(ScriptedSpeaker):
        async def speak(self, text):
            order.append("speak")
            async for chunk in super().speak(text):
                yield chunk

    connector = RecordingConnector([LiveEvent(turn_complete=True)])
    sink = CollectingEventSink()
    session = GeminiLiveAgentSession(sink, live_connector=connector, speaker=RecordingSpeaker())
    transport = FakeAudioTransport()
    registry = FakeToolRegistry({})

    await session.run(_spec(), transport, registry, ScriptedModerator(), CTX)

    assert order == ["speak", "connect"]


async def test_tool_call_round_trips_through_the_guarded_handler():
    handler = FakeHandler(result={"ok": True, "booked": True, "slot": "10am"})
    registry = FakeToolRegistry({"calendar": handler})
    connector = FakeLiveConnector(
        [
            function_call("call-1", "calendar", date="tomorrow"),
            LiveEvent(turn_complete=True),
        ]
    )
    session, moderator = _session(connector)
    transport = FakeAudioTransport()

    outcome = await session.run(_spec(), transport, registry, moderator, CTX)

    assert handler.calls[0][0] == {"date": "tomorrow"}
    # the registry resolved context — never the model choosing its own tenant.
    assert registry.resolved[0][0] == "calendar"
    assert registry.resolved[0][1].tenant_id == "t1"
    # the result was sent back to Live, id-correlated.
    assert connector.connection.tool_responses == [
        [{"id": "call-1", "name": "calendar", "response": {"ok": True, "booked": True, "slot": "10am"}}]
    ]
    assert outcome == LiveOutcome.BOOKED

    sink_events = session._sink.events
    types = [e.type for e in sink_events]
    assert EventType.TOOL_INVOKED in types
    assert EventType.SLOT_BOOKED in types
    assert EventType.LEAD_OUTCOME in types


async def test_a_rejected_tool_call_trips_a_guardrail_event_and_feeds_the_error_back():
    handler = FakeHandler(error=ValueError("outside calling hours"))
    registry = FakeToolRegistry({"calendar": handler})
    connector = FakeLiveConnector(
        [function_call("call-1", "calendar", date="tomorrow"), LiveEvent(turn_complete=True)]
    )
    session, moderator = _session(connector)
    transport = FakeAudioTransport()

    await session.run(_spec(), transport, registry, moderator, CTX)

    [responses] = connector.connection.tool_responses
    assert responses[0]["response"]["ok"] is False
    assert "outside calling hours" in responses[0]["response"]["error"]
    guardrail_events = session._sink.of_type(EventType.GUARDRAIL_TRIPPED)
    assert len(guardrail_events) == 1
    assert guardrail_events[0].payload["tool"] == "calendar"


async def test_moderation_block_cuts_playback_and_never_reaches_the_transport():
    connector = FakeLiveConnector(
        [
            LiveEvent(output_transcript_delta="Sure, here is a "),
            LiveEvent(output_transcript_delta="dangerous promise", audio=b"chunk-1"),
            LiveEvent(turn_complete=True),
        ]
    )
    moderator = ScriptedModerator({"dangerous promise": ModerationVerdict.BLOCK})
    session, _ = _session(connector, moderator)
    transport = FakeAudioTransport()
    registry = FakeToolRegistry({})

    await session.run(_spec(), transport, registry, moderator, CTX)

    assert b"chunk-1" not in transport.sent_audio
    assert transport.cut_count >= 1
    assert connector.connection.steers  # steered back on guardrail
    mod_events = [e for e in transport.events if e.get("type") == "moderation"]
    assert mod_events and mod_events[0]["verdict"] == "block"
    guardrail_events = session._sink.of_type(EventType.GUARDRAIL_TRIPPED)
    assert any(e.payload.get("reason") == "moderation_block" for e in guardrail_events)


async def test_moderation_flag_does_not_cut_playback():
    connector = FakeLiveConnector(
        [
            LiveEvent(output_transcript_delta="borderline phrase", audio=b"chunk-1"),
            LiveEvent(turn_complete=True),
        ]
    )
    moderator = ScriptedModerator({"borderline": ModerationVerdict.FLAG})
    session, _ = _session(connector, moderator)
    transport = FakeAudioTransport()
    registry = FakeToolRegistry({})

    await session.run(_spec(), transport, registry, moderator, CTX)

    assert b"chunk-1" in transport.sent_audio
    assert transport.cut_count == 0
    mod_events = [e for e in transport.events if e.get("type") == "moderation"]
    assert mod_events and mod_events[0]["verdict"] == "flag"


async def test_agent_audio_is_forwarded_to_the_transport():
    connector = FakeLiveConnector(
        [LiveEvent(output_transcript_delta="hi", audio=b"agent-chunk"), LiveEvent(turn_complete=True)]
    )
    session, moderator = _session(connector)
    transport = FakeAudioTransport()
    registry = FakeToolRegistry({})

    await session.run(_spec(), transport, registry, moderator, CTX)

    assert b"agent-chunk" in transport.sent_audio
    transcripts = [e for e in transport.events if e.get("type") == "transcript" and e["role"] == "agent"]
    assert transcripts and transcripts[0]["text"] == "hi"


async def test_native_barge_in_cuts_playback():
    connector = FakeLiveConnector([LiveEvent(interrupted=True), LiveEvent(turn_complete=True)])
    session, moderator = _session(connector)
    transport = FakeAudioTransport()
    registry = FakeToolRegistry({})

    await session.run(_spec(), transport, registry, moderator, CTX)

    assert transport.cut_count == 1


async def test_dnc_opt_out_ends_the_call_with_a_fixed_ack_bypassing_live():
    connector = FakeLiveConnector(
        [
            LiveEvent(input_transcript_delta="please stop calling me"),
            # if the call didn't end here, Live would keep going — it must not.
            LiveEvent(output_transcript_delta="Sure, let's keep chatting", audio=b"should-not-send"),
            LiveEvent(turn_complete=True),
        ]
    )
    session, moderator = _session(connector)
    speaker: ScriptedSpeaker = session._speaker
    transport = FakeAudioTransport()
    registry = FakeToolRegistry({})

    outcome = await session.run(_spec(), transport, registry, moderator, CTX)

    assert outcome == LiveOutcome.OPTED_OUT
    assert speaker.spoken[-1] == OPT_OUT_ACK
    assert b"should-not-send" not in transport.sent_audio
    lead_outcome_events = session._sink.of_type(EventType.LEAD_OUTCOME)
    assert lead_outcome_events[-1].payload["outcome"] == "opted_out"


async def test_call_lifecycle_events_are_emitted_in_order():
    connector = FakeLiveConnector([LiveEvent(turn_complete=True)])
    session, moderator = _session(connector)
    transport = FakeAudioTransport()
    registry = FakeToolRegistry({})

    await session.run(_spec(), transport, registry, moderator, CTX)

    types = [e.type for e in session._sink.events]
    assert types == [
        EventType.CALL_STARTED,
        EventType.DISCLOSURE_SPOKEN,
        EventType.LEAD_OUTCOME,
        EventType.CALL_ENDED,
    ]
    for e in session._sink.events:
        assert e.tenant_id == "t1"
        assert e.agent_id == "a1"
        assert e.call_id  # minted once per run(), non-empty


async def test_transport_is_started_and_ended_even_when_live_stream_is_empty():
    connector = FakeLiveConnector([])
    session, moderator = _session(connector)
    transport = FakeAudioTransport()
    registry = FakeToolRegistry({})

    await session.run(_spec(), transport, registry, moderator, CTX)

    assert transport.started
    assert transport.ended
    assert connector.exited
