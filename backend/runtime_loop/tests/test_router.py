"""SSE endpoint tests (router.py) via FastAPI TestClient — no server needed."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from backend.runtime_loop.demo_app import build_app
from backend.runtime_loop.fixtures import sample_ready_config


def _events(sse_text: str) -> list[tuple[str, dict]]:
    """Parse an SSE body into (event, data) pairs."""
    out: list[tuple[str, dict]] = []
    for block in sse_text.strip().split("\n\n"):
        event, data = None, {}
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if event:
            out.append((event, data))
    return out


def test_preview_streams_tokens_and_disclosure():
    client = TestClient(build_app())
    resp = client.post("/agents/agent-1/preview/messages", json={"message": "Hello?"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _events(resp.text)
    kinds = [e for e, _ in events]
    assert kinds[0] == "session"
    assert "token" in kinds
    assert kinds[-1] == "done"

    streamed = "".join(d["text"] for e, d in events if e == "token")
    disclosure = sample_ready_config().conversation.disclosure.disclosure_script
    assert disclosure in streamed


def test_unknown_agent_returns_typed_error_not_stream():
    client = TestClient(build_app())
    resp = client.post("/agents/nope/preview/messages", json={"message": "hi"})
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["kind"] == "validation"
    assert "message" in body["error"]


def test_session_id_is_returned_and_reusable():
    client = TestClient(build_app())
    r1 = client.post("/agents/agent-1/preview/messages", json={"message": "Hi"})
    sid = _events(r1.text)[0][1]["session_id"]

    r2 = client.post(
        "/agents/agent-1/preview/messages",
        json={"message": "Tell me more", "session_id": sid},
    )
    events = _events(r2.text)
    assert events[0] == ("session", {"session_id": sid})
    # Disclosure fired on turn 1, so it must NOT repeat on turn 2 (same session).
    streamed = "".join(d["text"] for e, d in events if e == "token")
    disclosure = sample_ready_config().conversation.disclosure.disclosure_script
    assert disclosure not in streamed
