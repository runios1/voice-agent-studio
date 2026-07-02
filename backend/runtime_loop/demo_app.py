"""Minimal runnable demo app for the preview surface (for the /verify skill).

Wires the runtime router with a MOCK wrapper (ScriptedWrapper) and a MOCK config
provider (a single fixture agent). This is NOT the integrated app — WS6 supplies the
real wrapper and WS2 the real config provider + auth at integration time. It exists
so the SSE preview endpoint can be exercised end-to-end today.

Run:  uvicorn backend.runtime_loop.demo_app:app   (or drive it with fastapi TestClient)
"""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, Request

from contracts.config_schema.schema import AgentConfig

from backend.runtime_loop.engine import RuntimeEngine
from backend.runtime_loop.fixtures import sample_ready_config
from backend.runtime_loop.mocks import ScriptedWrapper
from backend.runtime_loop.router import build_preview_router

# A canned agent reply that, if the model were honoring a hostile persona, would try
# to skip disclosure entirely — proving the code-emitted disclosure still lands.
_DEMO_REPLY = "Great to connect! Is now a good time for a quick chat about Acme?"

_CONFIG = sample_ready_config()


async def _config_provider(agent_id: str, user_id: str) -> Optional[AgentConfig]:
    # Tenant scoping demo: only the fixture owner may load the fixture agent.
    if agent_id == _CONFIG.meta.id and user_id == _CONFIG.meta.owner_user_id:
        return _CONFIG
    return None


async def _auth(request: Request) -> str:
    # Mock auth: fixed authed user. Real auth arrives at integration; the router
    # NEVER reads a client-supplied owner id (D-security).
    return "user-1"


def build_app() -> FastAPI:
    app = FastAPI(title="voice-agent-studio — runtime preview (demo)")
    engine = RuntimeEngine(ScriptedWrapper(_DEMO_REPLY))
    app.include_router(build_preview_router(engine, _config_provider, _auth))
    return app


app = build_app()
