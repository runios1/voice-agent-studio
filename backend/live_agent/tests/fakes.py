"""Test doubles for the P4-2 session runtime. No network, no `google.genai` import
anywhere in this module — that is the whole point of testing against the small
internal `LiveConnection` seam instead of the SDK."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional

from contracts.live_agent.interface import ModerationVerdict
from contracts.tool_registry.interface import ToolContext

from backend.live_agent.live_connection import LiveEvent, LiveFunctionCall


class FakeAudioTransport:
    """A double `AudioTransport`. `mic_chunks` are yielded once by `recv_audio`, then
    the mic "stays open" (blocks forever) so tests can rely on the Live side (the
    scripted event list ending) to end the call, exactly like a real open mic."""

    def __init__(self, mic_chunks: Optional[list[bytes]] = None) -> None:
        self._mic_chunks = mic_chunks or []
        self.started = False
        self.ended = False
        self.sent_audio: list[bytes] = []
        self.events: list[dict] = []
        self.cut_count = 0

    async def start(self) -> None:
        self.started = True

    async def send_audio(self, pcm: bytes) -> None:
        self.sent_audio.append(pcm)

    async def recv_audio(self) -> AsyncIterator[bytes]:
        for chunk in self._mic_chunks:
            yield chunk
        await asyncio.Event().wait()  # simulate an open mic; cancelled at call end

    async def send_event(self, event: dict) -> None:
        self.events.append(event)

    async def cut_playback(self) -> None:
        self.cut_count += 1

    async def end(self) -> None:
        self.ended = True


class FakeLiveConnection:
    """Yields a pre-scripted `events` list from `receive()`; records everything sent
    into it so a test can assert on the function-call/tool-response/steer round-trip."""

    def __init__(self, events: list[LiveEvent]) -> None:
        self._events = events
        self.sent_mic_audio: list[bytes] = []
        self.tool_responses: list[list[dict]] = []
        self.steers: list[str] = []

    async def send_audio(self, pcm: bytes) -> None:
        self.sent_mic_audio.append(pcm)

    async def send_tool_response(self, responses: list[dict]) -> None:
        self.tool_responses.append(responses)

    async def send_steer(self, instruction: str) -> None:
        self.steers.append(instruction)

    async def receive(self) -> AsyncIterator[LiveEvent]:
        for event in self._events:
            yield event


class FakeLiveConnector:
    """A `LiveConnector`: calling it (as `session.py` does, `self._live_connector(spec)`)
    returns itself, an async context manager yielding one `FakeLiveConnection` scripted
    with `events`."""

    def __init__(self, events: list[LiveEvent]) -> None:
        self.events = events
        self.connection: Optional[FakeLiveConnection] = None
        self.entered = False
        self.exited = False

    def __call__(self, spec) -> "FakeLiveConnector":
        return self

    async def __aenter__(self) -> FakeLiveConnection:
        self.entered = True
        self.connection = FakeLiveConnection(self.events)
        return self.connection

    async def __aexit__(self, *exc_info) -> None:
        self.exited = True


class FakeHandler:
    """A `ToolHandler` double. Raises `error` if set (simulating a guardrail
    rejection), else returns `result` (default `{"ok": True}`)."""

    def __init__(self, result: Optional[dict] = None, error: Optional[Exception] = None) -> None:
        self.result = result if result is not None else {"ok": True}
        self.error = error
        self.calls: list[tuple[dict, ToolContext]] = []

    async def execute(self, args: dict, ctx: ToolContext) -> dict:
        self.calls.append((args, ctx))
        if self.error is not None:
            raise self.error
        return self.result


class FakeToolRegistry:
    """A `ToolRegistry` double with `resolve_context`, mirroring the real registry's
    contract-extension (duck-typed, per `_resolve_tool_context`)."""

    def __init__(self, handlers: dict[str, FakeHandler]) -> None:
        self._handlers = handlers
        self.resolved: list[tuple[str, ToolContext]] = []

    def list_tools(self, timing=None):
        return []

    def get(self, name: str):
        return None

    def handler_for(self, name: str) -> FakeHandler:
        return self._handlers[name]

    def resolve_context(self, name, tenant_id, *, campaign_id=None, lead_id=None) -> ToolContext:
        ctx = ToolContext(tenant_id=tenant_id, campaign_id=campaign_id, lead_id=lead_id)
        self.resolved.append((name, ctx))
        return ctx


class ScriptedModerator:
    """A `StreamModerator` double: returns the first matching verdict whose needle is
    a substring of the cumulative text seen so far, else `default` (ALLOW)."""

    def __init__(
        self,
        verdicts_by_needle: Optional[dict[str, ModerationVerdict]] = None,
        *,
        default: ModerationVerdict = ModerationVerdict.ALLOW,
    ) -> None:
        self._map = verdicts_by_needle or {}
        self.default = default
        self.calls: list[str] = []

    async def check(self, cumulative_text: str) -> ModerationVerdict:
        self.calls.append(cumulative_text)
        for needle, verdict in self._map.items():
            if needle in cumulative_text:
                return verdict
        return self.default


def function_call(call_id: str, name: str, **args) -> LiveEvent:
    """Convenience: one Live event carrying a single function call."""
    return LiveEvent(function_calls=[LiveFunctionCall(id=call_id, name=name, args=args)])
