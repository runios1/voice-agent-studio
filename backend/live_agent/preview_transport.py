"""Browser `AudioTransport` + WS router for the Live-native preview (P4-4).

Where P3-4's `BrowserVoiceTransport` had to bridge browser audio <-> the text turn
loop (STT in, TTS out) around a `CallEngine`, this transport has nothing to bridge:
Gemini Live IS the agent (`contracts/live_agent`), so raw PCM just flows straight
through in both directions. One WS connection == one `LiveAgentSession.run(...)`
(P4-2, injected — not built yet, so this module only depends on the frozen
`Protocol`s and is exercised in tests against a fake session).

Reused UNCHANGED from `contracts/voice_preview` (the frozen Phase-3 wire): the audio
format (16 kHz in / 24 kHz out, PCM s16le), the route shape, and the `start`/`stop`/
`transcript`/`disclosure`/`outcome`/`error`/`ended` JSON message vocabulary — this
router forwards those exactly as before.

ADDITIVE wire extension (new for Phase 4; documented in
`docs/contract-change-requests/p4-4-live-preview-events.md` rather than silently
edited into the frozen `contracts/voice_preview/protocol.py`): three new JSON
message shapes a `LiveAgentSession` (P4-2) sends via `AudioTransport.send_event`
for the UI to render:

    {"type": "tool", "name": <str>, "timing": "in_call" | "post_call"}
    {"type": "moderation", "verdict": "flag" | "block"}
    {"type": "cut_playback"}

`cut_playback` is emitted by `PreviewAudioTransport.cut_playback()` itself (the
`AudioTransport.cut_playback` contract method) — a dedicated, unambiguous signal the
frontend uses to flush whatever agent audio it has already buffered/scheduled the
instant a moderation BLOCK fires, independent of whatever `moderation` display frame
the session also chooses to send via `send_event`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Awaitable, Callable, Optional, Protocol

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from contracts.config_schema.schema import AgentConfig
from contracts.events.schema import Event
from contracts.live_agent.interface import (
    LiveAgentCompiler,
    LiveAgentSession,
    LiveCallContext,
    StreamModerator,
)
from contracts.tool_registry.interface import ToolRegistry

from backend.config_gate.api import current_user
from backend.voice_runtime.events import EventSink

log = logging.getLogger("voice_agent_studio.live_agent.preview")

SendJSON = Callable[[dict], Awaitable[None]]
SendAudio = Callable[[bytes], Awaitable[None]]


class ConfigSource(Protocol):
    """Matches `backend.integration.config_source.AgentServiceConfigSource` (same
    seam P3-4 used) — tenant-scoped in the caller's code, never by a client-supplied
    owner id."""

    def get_config(self, agent_id: str, tenant_id: str) -> Optional[AgentConfig]: ...


class RegistryBuilder(Protocol):
    """Matches `backend.integration.runtime.ToolStack` — only enabled automation
    yields a live tool declaration (structural denial preserved end to end)."""

    def registry_for(self, config: AgentConfig, sink: EventSink) -> ToolRegistry: ...


class PreviewAudioTransport:
    """The frozen `AudioTransport` (`contracts/live_agent`) for one browser preview
    call. Audio passes straight through in both directions — no STT/TTS bridge, Live
    hears/speaks natively. Inbound audio has exactly one reader (the router's own WS
    receive loop, matching P3-4's `BrowserVoiceTransport`), so it is PUSHED in via
    `push_audio`/`push_stop`, buffered in a queue, and drained by the session through
    `recv_audio`."""

    def __init__(self, send_json: SendJSON, send_audio: SendAudio) -> None:
        self._send_json = send_json
        self._send_audio = send_audio
        self._queue: "asyncio.Queue[Optional[bytes]]" = asyncio.Queue()
        self._stopped = False

    async def start(self) -> None:
        return None

    async def send_audio(self, pcm: bytes) -> None:
        await self._send_audio(pcm)

    async def recv_audio(self) -> AsyncIterator[bytes]:
        while True:
            chunk = await self._queue.get()
            if chunk is None:
                return
            yield chunk

    async def send_event(self, event: dict) -> None:
        await self._send_json(event)

    async def cut_playback(self) -> None:
        # See module docstring: a dedicated signal, distinct from any `moderation`
        # display frame the session sends separately via `send_event`.
        await self._send_json({"type": "cut_playback"})

    async def end(self) -> None:
        return None

    # ---- fed by the router's single WS-receive loop; the session never calls these --- #
    async def push_audio(self, chunk: bytes) -> None:
        if self._stopped:
            return
        self._queue.put_nowait(chunk)

    def push_stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._queue.put_nowait(None)


class _SerializedSender:
    """One WebSocket has one connection; the session's own task and this router's
    receive loop both write to it concurrently (agent audio/events vs. reading lead
    audio doesn't write back, but `end`/`error`/`ended` frames race the session's own
    sends) — serialize every outbound frame through a lock, same posture as P3-4."""

    def __init__(self, websocket: WebSocket) -> None:
        self._websocket = websocket
        self._lock = asyncio.Lock()
        self._closed = False  # set once the client is gone; every later send is a no-op

    async def send_json(self, data: dict) -> None:
        await self._guarded(lambda: self._websocket.send_json(data))

    async def send_bytes(self, data: bytes) -> None:
        await self._guarded(lambda: self._websocket.send_bytes(data))

    async def _guarded(self, send) -> None:
        """A hung-up client is a normal end, not an error: once the socket is closed,
        swallow the disconnect (and every subsequent send) so the session can wind down
        cleanly instead of a send raising into — and crashing — the run task. (D)"""
        if self._closed:
            return
        async with self._lock:
            if self._closed:
                return
            try:
                await send()
            except (WebSocketDisconnect, RuntimeError, ConnectionError):
                self._closed = True


class _ForwardingSink:
    """Wraps the real `EventSink` so every event STILL reaches the compliance log AND is
    mirrored to the browser as an `{"type": "event", "event": {...}}` frame. That lets the
    preview render a live, dashboard-identical view of THIS call (the frontend folds the
    same events the ops dashboard does). The forwarded event is the exact wire shape the
    dashboard consumes off its SSE stream (`Event.model_dump(mode="json")`). A send failure
    (client already gone) is swallowed — the event is still recorded upstream, so the
    compliance record never depends on the browser being present."""

    def __init__(self, inner: EventSink, sender: "_SerializedSender") -> None:
        self._inner = inner
        self._sender = sender

    async def emit(self, event: Event) -> None:
        await self._inner.emit(event)
        try:
            await self._sender.send_json(
                {"type": "event", "event": event.model_dump(mode="json")}
            )
        except Exception:  # pragma: no cover - defensive; sender already swallows normal drops
            log.debug("preview event not forwarded (client gone): %s", event.type)


def create_router(
    config_source: ConfigSource,
    registry_builder: RegistryBuilder,
    compiler: LiveAgentCompiler,
    sink: EventSink,
    *,
    session_factory: Callable[[EventSink], LiveAgentSession],
    moderator_factory: Callable[[], StreamModerator],
) -> APIRouter:
    """Factory so the config source, tool registry builder, compiler, and event sink
    are injected — real singletons at integration, fakes in tests. `session_factory`/
    `moderator_factory` build a FRESH instance per call (a Live session and its
    moderator both carry per-call state); they are required, not defaulted, because
    the real P4-2/P4-3 implementations don't exist in this workstream — callers pass
    a fake in tests and the real thing at integration, once merged.

    `session_factory` receives the PER-CONNECTION sink (`_ForwardingSink` wrapping the
    injected `sink`) so the session's events reach both the compliance log and the
    browser — the session and its tool registry must share that one sink."""
    router = APIRouter()

    @router.websocket("/agents/{agent_id}/preview/voice")
    async def preview_voice(
        websocket: WebSocket, agent_id: str, user_id: str = Depends(current_user)
    ) -> None:
        await websocket.accept()

        config = config_source.get_config(agent_id, user_id)
        if config is None:
            await websocket.send_json({"type": "error", "message": "That agent doesn't exist."})
            await websocket.close()
            return

        try:
            first = await websocket.receive()
        except WebSocketDisconnect:
            return
        if first.get("type") == "websocket.disconnect":
            return
        if not _is_control(first, "start"):
            await websocket.send_json(
                {"type": "error", "message": "Expected a 'start' message first."}
            )
            await websocket.close()
            return

        sender = _SerializedSender(websocket)
        # One per-connection sink: events reach the compliance log AND mirror to this
        # browser as `event` frames (the live preview dashboard). The session and its
        # tool registry share it so BOTH their events (call.started/slot.booked/... and
        # tool.invoked) show up in the preview's dashboard view.
        forwarding_sink = _ForwardingSink(sink, sender)
        spec = compiler.compile(config)
        registry = registry_builder.registry_for(config, forwarding_sink)
        ctx = LiveCallContext(tenant_id=user_id, agent_id=agent_id, campaign_id="preview")
        transport = PreviewAudioTransport(sender.send_json, sender.send_bytes)
        session = session_factory(forwarding_sink)
        moderator = moderator_factory()

        run = asyncio.ensure_future(
            session.run(spec, transport, registry, moderator, ctx)
        )
        # End the call when EITHER side hangs up: the caller (the inbound loop returns on
        # a 'stop' / socket close) or the AGENT (run() completes after an end_call). Race
        # them so an agent-initiated hang-up isn't blocked waiting on the caller to close.
        inbound = asyncio.ensure_future(_pump_inbound(websocket, transport))
        try:
            await asyncio.wait({run, inbound}, return_when=asyncio.FIRST_COMPLETED)
        except Exception:
            log.exception("preview inbound loop failed for %s", agent_id)
        transport.push_stop()  # unblock the mic pump so run() can finish
        if not inbound.done():
            inbound.cancel()

        try:
            outcome = await run
        except Exception:
            log.exception("live preview call %s failed", agent_id)
            await _safe_send_json(
                websocket, {"type": "error", "message": "The call hit a problem and ended."}
            )
            await _safe_send_json(websocket, {"type": "ended"})
            await _safe_close(websocket)
            return

        await _safe_send_json(
            websocket,
            {"type": "ended", "outcome": outcome.value if outcome else None},
        )
        await _safe_close(websocket)

    return router


async def _pump_inbound(websocket: WebSocket, transport: PreviewAudioTransport) -> None:
    """The single reader on this socket: binary frames are lead audio, text frames are
    control (only `stop` matters — anything else is ignored, forward-compatible)."""
    while True:
        try:
            message = await websocket.receive()
        except WebSocketDisconnect:
            return
        if message.get("type") == "websocket.disconnect":
            return
        data = message.get("bytes")
        if data is not None:
            await transport.push_audio(data)
            continue
        text = message.get("text")
        if text is not None and _is_control(message, "stop"):
            return


async def _safe_send_json(websocket: WebSocket, data: dict) -> None:
    try:
        await websocket.send_json(data)
    except Exception:
        pass  # client already gone; nothing further to do


async def _safe_close(websocket: WebSocket) -> None:
    try:
        await websocket.close()
    except Exception:
        pass


def _is_control(message: dict, expected_type: str) -> bool:
    text = message.get("text")
    if text is None:
        return False
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return False
    return payload.get("type") == expected_type
