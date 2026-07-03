"""FastAPI router for the browser-voice preview (P3-4).

Exposes `WS /agents/{agent_id}/preview/voice` per `contracts/voice_preview` (the
integrator mounts it under `/api`, per the boundary in this package's README — this
module never touches `integrated_app.py`).

One connection == one `CallEngine.run_call` over a `BrowserVoiceTransport`, so the
code-emitted disclosure, in-call tools, and event trail are IDENTICAL to a real call
(the contract's non-negotiable design intent). This module's whole job is translating
between the WS wire protocol and that call: fetch the caller's own built config
(tenant-scoped, D-security), run the engine, forward the handful of lifecycle events
the UI needs as `disclosure` / `outcome` / `ended` frames, and turn any failure into a
calm `error` frame — never a stack trace (D-reliability).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Callable, Optional, Protocol

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from contracts.campaign.model import Lead
from contracts.config_schema.schema import AgentConfig
from contracts.events.schema import Event, EventType
from contracts.model_wrapper.interface import ModelWrapper

from backend.config_gate.api import current_user
from backend.voice_runtime.engine import CallEngine
from backend.voice_runtime.events import EventSink
from backend.voice_preview.speech_bridge import SpeechBridge, build_speech_bridge
from backend.voice_preview.transport import BrowserVoiceTransport

log = logging.getLogger("voice_agent_studio.voice_preview")

# Events the UI badges/needs; anything else (call.started, tool.invoked, ...) still
# reaches the shared sink (the compliance record) but has no wire-protocol frame.
_FORWARD: dict[EventType, Callable[[dict], dict]] = {
    EventType.DISCLOSURE_SPOKEN: lambda payload: {"type": "disclosure"},
    EventType.LEAD_OUTCOME: lambda payload: {"type": "outcome", "outcome": payload["outcome"]},
}


class ConfigSource(Protocol):
    """Matches `backend.integration.config_source.AgentServiceConfigSource` — the
    SAME seam the campaign orchestrator uses, so the preview runs the one config
    artifact the builder loop edits (`get_config` is tenant-scoped in the caller's
    code, never by a client-supplied owner id)."""

    def get_config(self, agent_id: str, tenant_id: str) -> Optional[AgentConfig]: ...


class RegistryBuilder(Protocol):
    """Matches `backend.integration.runtime.ToolStack` — builds the per-agent tool
    registry (only enabled automation yields a live tool, same structural denial as
    a real call)."""

    def registry_for(self, config: AgentConfig, sink: EventSink): ...


class _ForwardingSink:
    """Wraps the app's real `EventSink` so every event still reaches the compliance
    log (even if the browser disconnects mid-call), while forwarding the subset the
    wire protocol names as a JSON frame. A send failure (client already gone) is
    swallowed — the call keeps running and the event is still recorded upstream."""

    def __init__(self, inner: EventSink, websocket: WebSocket) -> None:
        self._inner = inner
        self._websocket = websocket

    async def emit(self, event: Event) -> None:
        await self._inner.emit(event)
        make = _FORWARD.get(event.type)
        if make is None:
            return
        try:
            await self._websocket.send_json(make(event.payload))
        except Exception:
            log.debug("preview socket gone; %s not delivered", event.type.value)


class _SerializedSender:
    """One WebSocket has one connection; a `CallEngine` call and this router's own
    receive loop both write to it (agent speech vs. lead transcript), from two
    different coroutines. Serializing every outbound frame through a lock avoids
    interleaving partial writes — awaiting `websocket.send*` can yield control
    mid-write, so two concurrent callers are not automatically safe."""

    def __init__(self, websocket: WebSocket) -> None:
        self._websocket = websocket
        self._lock = asyncio.Lock()

    async def send_json(self, data: dict) -> None:
        async with self._lock:
            await self._websocket.send_json(data)

    async def send_bytes(self, data: bytes) -> None:
        async with self._lock:
            await self._websocket.send_bytes(data)


def create_router(
    config_source: ConfigSource,
    registry_builder: RegistryBuilder,
    model: ModelWrapper,
    sink: EventSink,
    *,
    speech_bridge_factory: Callable[[], SpeechBridge] = build_speech_bridge,
) -> APIRouter:
    """Factory so the config source, tool registry builder, model wrapper, and event
    sink are injected — real singletons at integration (the SAME ones a campaign
    uses), fakes in tests. `speech_bridge_factory` defaults to the env-gated
    mock<->real switch; tests override it with a scripted double."""
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
        forwarding_sink = _ForwardingSink(sink, websocket)
        lead = Lead(
            id=uuid.uuid4().hex,
            campaign_id="preview",
            tenant_id=user_id,
            phone="",  # no PSTN leg for a browser preview; Lead.phone is non-optional
            display_name="Preview",
        )
        registry = registry_builder.registry_for(config, forwarding_sink)
        engine = CallEngine(model, forwarding_sink, model_tier="voice")
        transport = BrowserVoiceTransport(
            speech_bridge_factory(), sender.send_json, sender.send_bytes
        )

        run = asyncio.ensure_future(engine.run_call(config, lead, transport, registry))
        try:
            await _pump_inbound(websocket, transport)
        except Exception:
            log.exception("preview inbound loop failed for %s", agent_id)
        transport.push_stop()

        try:
            session = await run
        except Exception:
            log.exception("preview call %s failed", agent_id)
            await _safe_send_json(
                websocket, {"type": "error", "message": "The call hit a problem and ended."}
            )
            await _safe_send_json(websocket, {"type": "ended"})
            await _safe_close(websocket)
            return

        await _safe_send_json(
            websocket,
            {"type": "ended", "outcome": session.outcome.value if session.outcome else None},
        )
        await _safe_close(websocket)

    return router


async def _pump_inbound(websocket: WebSocket, transport: BrowserVoiceTransport) -> None:
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
