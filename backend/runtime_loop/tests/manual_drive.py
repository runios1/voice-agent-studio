"""Manual verification: drive the preview SSE endpoint as a real HTTP client.

Exercises the full FastAPI app (routing, body parsing, StreamingResponse) over an
httpx ASGI transport — not the engine in isolation. Captures raw SSE bytes for the
happy path, session reuse, an injected-persona attempt (which must NOT suppress the
code-emitted disclosure), and error probes.

Run:  python3 backend/runtime_loop/tests/manual_drive.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import httpx
from fastapi import FastAPI, Request

from contracts.config_schema.schema import AgentConfig

from backend.runtime_loop.engine import RuntimeEngine
from backend.runtime_loop.fixtures import sample_ready_config
from backend.runtime_loop.mocks import ScriptedWrapper
from backend.runtime_loop.router import build_preview_router


def make_app(agent_reply: str, config: AgentConfig) -> FastAPI:
    app = FastAPI()

    async def provider(agent_id: str, user_id: str) -> Optional[AgentConfig]:
        if agent_id == config.meta.id and user_id == config.meta.owner_user_id:
            return config
        return None

    async def auth(request: Request) -> str:
        return "user-1"

    engine = RuntimeEngine(ScriptedWrapper(agent_reply))
    app.include_router(build_preview_router(engine, provider, auth))
    return app


async def call(client, path, body):
    print(f"\n>>> POST {path}  body={body}")
    async with client.stream("POST", path, json=body) as r:
        ctype = r.headers.get("content-type", "")
        print(f"<<< status {r.status_code}  content-type={ctype}")
        buf = b""
        async for chunk in r.aiter_bytes():
            buf += chunk
        text = buf.decode()
        print("--- raw SSE ---" if ctype.startswith("text/event-stream") else "--- body ---")
        print(text.rstrip())
        return r.status_code, text


def _session_id(sse_text: str) -> Optional[str]:
    for block in sse_text.split("\n\n"):
        if "event: session" in block:
            for line in block.splitlines():
                if line.startswith("data: "):
                    return json.loads(line[6:])["session_id"]
    return None


async def main():
    config = sample_ready_config()
    disclosure = config.conversation.disclosure.disclosure_script

    # A HOSTILE model reply: pretends to be human, never discloses AI on its own.
    hostile = "Hi! I'm Riley, a real human here at Acme. I am definitely not a bot."
    transport = httpx.ASGITransport(app=make_app(hostile, config))
    async with httpx.AsyncClient(transport=transport, base_url="http://preview") as client:
        _, t1 = await call(client, "/agents/agent-1/preview/messages", {"message": "Are you a bot?"})
        print(f"\n[CHECK] disclosure present despite hostile 'human' reply: {disclosure in t1}")

        sid = _session_id(t1)
        _, t2 = await call(
            client, "/agents/agent-1/preview/messages",
            {"message": "ok tell me more", "session_id": sid},
        )
        print(f"[CHECK] disclosure NOT repeated on turn 2 (same session): {disclosure not in t2}")

        await call(client, "/agents/does-not-exist/preview/messages", {"message": "hi"})
        await call(client, "/agents/agent-1/preview/messages", {"nope": "missing message field"})


if __name__ == "__main__":
    asyncio.run(main())
