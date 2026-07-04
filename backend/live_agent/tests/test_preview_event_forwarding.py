"""The preview forwards its structured events to the browser (P4-4 live preview
dashboard). A real `GeminiLiveAgentSession` (scripted Live connection, no network) runs
over the preview WS; we assert the browser receives `{"type":"event","event":{...}}`
frames whose payloads carry the EXACT keys the dashboard's Call-details view folds
(`ended_reason`, `slot_start`, `tool_name:"email"`, `outcome`). If those ever drift, the
preview dashboard would silently mis-render — so this fails loudly instead.
"""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from contracts.events.schema import EventType
from contracts.live_agent.interface import LiveAgentSpec

from backend.config_gate.api import current_user
from backend.live_agent.live_connection import LiveEvent
from backend.live_agent.preview_transport import create_router
from backend.live_agent.session import GeminiLiveAgentSession
from backend.live_agent.speaker import ScriptedSpeaker
from backend.live_agent.tests.fakes import (
    FakeHandler,
    FakeLiveConnector,
    FakeToolRegistry,
    ScriptedModerator,
    function_call,
)
from backend.runtime_loop.fixtures import sample_ready_config
from backend.voice_runtime.events import CollectingEventSink

TENANT = "tenant-1"
AGENT = "agent-1"
DISCLOSURE = "This call may use an AI assistant."
SLOT_START = "2026-08-01T15:00:00Z"


class _ConfigSource:
    def get_config(self, agent_id, tenant_id):
        return None if tenant_id != TENANT else sample_ready_config(agent_id=agent_id)


class _RegistryBuilder:
    def __init__(self, registry):
        self._registry = registry

    def registry_for(self, config, sink):
        return self._registry


class _Compiler:
    def compile(self, config) -> LiveAgentSpec:
        return LiveAgentSpec(
            system_instruction="be a good SDR",
            disclosure_line=DISCLOSURE,
            tool_declarations=[],
            moderation_buffer_ms=0,
            post_call_email_template_id="tmpl-confirm",
        )


def _booking_connector() -> FakeLiveConnector:
    return FakeLiveConnector(
        [
            LiveEvent(output_transcript_delta=f"{DISCLOSURE} Hi from Acme.", audio=b"a"),
            LiveEvent(turn_complete=True),  # -> disclosure.spoken
            function_call("c1", "calendar", start_iso=SLOT_START),  # -> tool.invoked + slot.booked
            function_call("e1", "end_call", outcome="qualified"),  # -> hang up
            LiveEvent(turn_complete=True),
        ]
    )


def _build_app():
    calendar = FakeHandler(
        result={"ok": True, "booked": True, "start_iso": SLOT_START, "attendee_email": "l@x.com"}
    )
    registry = FakeToolRegistry({"calendar": calendar, "email": FakeHandler({"ok": True})})
    app = FastAPI()
    app.include_router(
        create_router(
            _ConfigSource(),
            _RegistryBuilder(registry),
            _Compiler(),
            CollectingEventSink(),  # inner compliance sink
            session_factory=lambda call_sink: GeminiLiveAgentSession(
                call_sink,
                live_connector=_booking_connector(),
                speaker=ScriptedSpeaker(chunk_size=1024),
            ),
            moderator_factory=ScriptedModerator,
        )
    )
    app.dependency_overrides[current_user] = lambda: TENANT
    return app


def _run_and_collect_event_frames(client: TestClient) -> list[dict]:
    events: list[dict] = []
    with client.websocket_connect(f"/agents/{AGENT}/preview/voice") as ws:
        ws.send_json({"type": "start"})
        while True:
            msg = ws.receive()
            if msg.get("bytes") is not None:
                continue
            text = msg.get("text")
            if text is None:
                break
            frame = json.loads(text)
            if frame.get("type") == "event":
                events.append(frame["event"])
            if frame.get("type") in ("ended", "error"):
                break
    return events


def test_preview_forwards_dashboard_shaped_events_to_the_browser():
    client = TestClient(_build_app())
    events = _run_and_collect_event_frames(client)

    by_type: dict[str, list[dict]] = {}
    for e in events:
        # each forwarded frame is a full Event (the dashboard's wire shape)
        assert {"event_id", "type", "occurred_at", "severity", "payload"} <= set(e)
        by_type.setdefault(e["type"], []).append(e)

    for required in (
        EventType.CALL_STARTED.value,
        EventType.DISCLOSURE_SPOKEN.value,
        EventType.SLOT_BOOKED.value,
        EventType.LEAD_OUTCOME.value,
        EventType.CALL_ENDED.value,
        EventType.TOOL_INVOKED.value,
    ):
        assert required in by_type, f"missing {required}; saw {sorted(by_type)}"

    # the exact payload keys frontend metrics.buildLeadRecords() reads:
    assert by_type[EventType.SLOT_BOOKED.value][0]["payload"]["slot_start"] == SLOT_START
    assert by_type[EventType.CALL_ENDED.value][0]["payload"]["ended_reason"] == "booked"
    assert by_type[EventType.LEAD_OUTCOME.value][0]["payload"]["outcome"] == "qualified"
    tool_names = {e["payload"].get("tool_name") for e in by_type[EventType.TOOL_INVOKED.value]}
    assert {"calendar", "email"} <= tool_names  # in-call booking + post-call confirmation
