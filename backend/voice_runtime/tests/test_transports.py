"""Transports — the reference text transport + the Retell seam guard."""

from __future__ import annotations

import pytest

from contracts.voice_runtime.interface import CallOutcome

from backend.voice_runtime.transports import MockVoiceTransport, RetellTransport, TextTransport


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
