"""P2-1 — Voice runtime.

Implements the frozen `contracts/voice_runtime` interface: run a bounded-autonomy
call for a (config, lead) over a `CallTransport`, keeping the Phase-1 durable parts
identical (code-emitted AI disclosure, deterministic prompt composition,
capability == an enabled function). See `engine.CallEngine`.
"""

from __future__ import annotations

from backend.voice_runtime.engine import CallEngine
from backend.voice_runtime.events import CollectingEventSink, EventSink
from backend.voice_runtime.transports import (
    MockVoiceTransport,
    RetellTransport,
    TextTransport,
)

__all__ = [
    "CallEngine",
    "EventSink",
    "CollectingEventSink",
    "TextTransport",
    "MockVoiceTransport",
    "RetellTransport",
]
