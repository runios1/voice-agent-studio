"""Drive a full voice call through the mock platform, end to end, and print the
transcript + the emitted event trail. This is the runnable surface for /verify:

    python3 backend/voice_runtime/tests/manual_drive.py

It runs three scenarios:
  1. A booking call  — disclosure fires first, the model calls the IN_CALL `calendar`
     tool, the slot books (BOOKED), and slot.booked is emitted.
  2. An opt-out call — the lead says "take me off your list"; the DNC guardrail fires
     in code, the agent acknowledges and the outcome is OPTED_OUT.
  3. A warm transfer — the lead asks for a human; escalate() transfers and the outcome
     is TRANSFERRED.

No real telephony and no real model — the voice platform (Retell) and the model
wrapper are mocked, per the workstream boundary.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.voice_runtime.engine import CallEngine  # noqa: E402
from backend.voice_runtime.events import CollectingEventSink  # noqa: E402
from backend.voice_runtime.fixtures import config_with_calendar, sample_lead  # noqa: E402
from backend.voice_runtime.mocks import (  # noqa: E402
    MockToolRegistry,
    ScriptedToolWrapper,
    tool_call,
)
from backend.voice_runtime.transports import MockVoiceTransport  # noqa: E402


def _print_call(title: str, transport: MockVoiceTransport, sink: CollectingEventSink, session) -> None:
    print(f"\n=== {title} ===")
    print("  transcript:")
    for line in transport.agent_lines:
        print(f"    AGENT: {line}")
    print("  events:")
    for e in sink.events:
        print(f"    - {e.type.value:22} {e.severity.value:8} {e.payload}")
    print(f"  OUTCOME: {session.outcome.value}")


async def booking_call() -> None:
    sink = CollectingEventSink()
    engine = CallEngine(
        ScriptedToolWrapper([
            "Riley here from Acme — is now a good moment to talk workflow automation?",
            tool_call("calendar", start_iso="2026-07-10T10:00:00"),
            "Perfect, you're booked for Friday at 10am. Talk soon!",
        ]),
        sink,
    )
    transport = MockVoiceTransport(["Sure. Friday at 10 works."])
    session = await engine.run_call(config_with_calendar(), sample_lead(), transport, MockToolRegistry())
    _print_call("1. BOOKING CALL", transport, sink, session)
    assert session.outcome.value == "booked"


async def opt_out_call() -> None:
    sink = CollectingEventSink()
    engine = CallEngine(ScriptedToolWrapper("Hi, Riley from Acme here."), sink)
    transport = MockVoiceTransport(["Please take me off your list."])
    session = await engine.run_call(config_with_calendar(), sample_lead(), transport, MockToolRegistry())
    _print_call("2. OPT-OUT (DNC) CALL", transport, sink, session)
    assert session.outcome.value == "opted_out"


async def transfer_call() -> None:
    sink = CollectingEventSink()
    engine = CallEngine(ScriptedToolWrapper("Hi, Riley from Acme here."), sink)
    transport = MockVoiceTransport(["Can I just talk to a human please?"])
    session = await engine.run_call(config_with_calendar(), sample_lead(), transport, MockToolRegistry())
    _print_call("3. WARM TRANSFER CALL", transport, sink, session)
    assert session.outcome.value == "transferred" and transport.transferred_to_human


async def main() -> None:
    await booking_call()
    await opt_out_call()
    await transfer_call()
    print("\nAll three scenarios behaved as expected.")


if __name__ == "__main__":
    asyncio.run(main())
