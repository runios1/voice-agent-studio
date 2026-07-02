"""FastAPI router for the preview surface (API contract: Runtime loop).

Implements `POST /agents/{id}/preview/messages` (SSE) — talk *to* the built agent
(not the builder). Streams the agent's response per its configured
persona/goal/guardrails. Phase 1: text only, no tools, no voice (D12).

Boundaries respected here:
  * Config loading + tenant scoping are WS2's domain — this router reaches them ONLY
    through an injected `ConfigProvider`, which it always calls with the AUTHED user
    id (from `auth`), never a client-supplied owner id (tenant isolation, D-security).
  * Errors degrade to the contract's typed error shape — never a stack trace
    (D-reliability). Pre-stream failures return JSON; mid-stream failures emit a
    calm SSE `error` event.

`build_preview_router` is a factory so the engine, config provider, and auth
dependency can be injected (real ones at integration; mocks in tests / the demo).
"""

from __future__ import annotations

import json
from typing import Awaitable, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from contracts.config_schema.schema import AgentConfig

from backend.runtime_loop.engine import RuntimeEngine

# agent_id + authed user_id -> the user's config, or None if not found/not owned.
ConfigProvider = Callable[[str, str], Awaitable[Optional[AgentConfig]]]
# request -> authed user id (WS-integration supplies the real session auth).
AuthDependency = Callable[[Request], Awaitable[str]]


class PreviewMessageRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _error(kind: str, message: str, path: str | None = None) -> dict:
    err: dict = {"kind": kind, "message": message}
    if path is not None:
        err["path"] = path
    return {"error": err}


def build_preview_router(
    engine: RuntimeEngine,
    config_provider: ConfigProvider,
    auth: AuthDependency,
) -> APIRouter:
    router = APIRouter()

    @router.post("/agents/{agent_id}/preview/messages")
    async def preview_messages(agent_id: str, body: PreviewMessageRequest, request: Request):
        user_id = await auth(request)

        # Tenant scoping in CODE: the provider is asked only for THIS user's agent.
        config = await config_provider(agent_id, user_id)
        if config is None:
            return JSONResponse(
                status_code=404,
                content=_error("validation", "That agent doesn't exist."),
            )

        session = engine.store.get_or_create(agent_id, body.session_id)

        async def event_stream():
            # Tell the client which session this is (lets it continue the thread).
            yield _sse("session", {"session_id": session.session_id})
            try:
                async for ev in engine.run_turn(config, session, body.message):
                    if ev.kind == "token":
                        yield _sse("token", {"text": ev.text})
                    elif ev.kind == "done":
                        yield _sse("done", {})
            except Exception:
                # Calm, typed, no stack trace (D-reliability). The screening layer
                # (WS5) surfaces its own screening_blocked/flagged kinds upstream.
                yield _sse(
                    "error",
                    _error("validation", "Sorry — I hit a problem responding. Try again?"),
                )

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return router
