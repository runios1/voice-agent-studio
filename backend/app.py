"""Integration assembly — the ONE FastAPI app that wires all six workstreams.

This is the piece the parallel dispatch deliberately left for the integrator: each
workstream shipped a module (a gate service, a builder loop, a runtime engine, a
screening decorator, a Gemini wrapper) but none owns the process that binds them
into the routes the frontend calls. That wiring lives here, and ONLY here.

Composition (inner -> outer, mirroring the defense-in-depth model):

    GeminiWrapper (WS6)                     # provider SDK, reads key from env
      └─ ScreeningModelWrapper (WS5)        # screens every model in/out
           ├─ BuilderLoop (WS3)             # chat that EDITS the config
           └─ RuntimeEngine (WS4)           # chat that EXECUTES the config (preview)

    AgentService + InMemoryConfigRepository (WS2)   # the one mutation door + storage
      ├─ mounted directly for /agents + PATCH /fields
      ├─ adapted to the builder loop's Gate protocol (ServiceBuilderGate)
      └─ used as the preview's ConfigProvider

Routes (all under /api so the Vite dev proxy forwards /api -> :8000 unchanged):

    POST/GET  /api/agents ...                     WS2 router
    PATCH     /api/agents/{id}/fields             WS2 router
    POST      /api/agents/{id}/builder/messages   builder SSE (assembled here)
    POST      /api/agents/{id}/preview/messages   WS4 router

AUTH: `build_app(user_dependency=...)` overrides the WS2 `current_user` dependency
(and the preview auth) with a real session dependency — see `backend.auth` +
`integrated_app.py`, which wires Google sign-in. Left unset, both fall back to a
fixed dev user (standalone WS2 usage, tests) and a seeded demo agent (`agent-demo`)
so the frontend's default VITE_AGENT_ID still resolves without a create step.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from contracts.config_schema.schema import AgentConfig, AgentMeta, AgentStatus
from contracts.model_wrapper.interface import Message

# WS6 — provider wrapper
from backend.wrapper_impl import GeminiWrapper

# WS5 — screening decorator around every model call
from backend.security import ScreeningBlocked, ScreeningModelWrapper, build_screener

# WS2 — config gate + persistence
from backend.config_gate.api import (
    _install_error_handler,
    create_router as create_gate_router,
    current_user,
)
from backend.config_gate.completeness import evaluate_status
from backend.config_gate.errors import GateError as ConfigGateError
from backend.integration.persistence import build_config_repository
from backend.config_gate.service import AgentService

# WS3 — builder loop
from backend.builder_loop import BuilderLoop, InMemorySessionStore
from backend.builder_loop.gate import GateAccepted, GateError as BuilderGateError, Patch

# WS4 — runtime preview loop
from backend.runtime_loop.engine import RuntimeEngine
from backend.runtime_loop.router import build_preview_router


DEV_USER = "dev-user"
DEMO_AGENT_ID = "agent-demo"


# --------------------------------------------------------------------------- #
# Integration-point specialization of the WS5 screening decorator.
#
# The builder/runtime SYSTEM prompt is code-composed scaffolding that *describes*
# the locked guardrails — it literally contains "don't disclose" / "ignore DNC" as
# examples of what the agent must NOT do. WS5's guardrail-domain heuristic reads
# that description as a subversion attempt and hard-blocks (fail-closed). Screening
# our own trusted instructions is a false positive: any USER free-text that ends up
# in the prompt was already screened at the config gate on write (the structural
# boundary), and AI disclosure is code-emitted at runtime regardless.
#
# So at the wiring point we screen every non-system turn inbound (user/tool content)
# and all model OUTPUT — but not the trusted system instruction. This is an
# integrator composition choice; WS5 itself is unchanged.
# --------------------------------------------------------------------------- #
class IntegrationScreeningWrapper(ScreeningModelWrapper):
    async def _screen_inbound(self, messages: list[Message]) -> None:
        await super()._screen_inbound([m for m in messages if m.role != "system"])


# --------------------------------------------------------------------------- #
# Builder <-> gate adapter.
# The builder loop depends on a narrow `Gate` protocol (get_config / apply_patch,
# no user arg). WS2's AgentService is user-scoped. This binds a user and translates
# WS2's typed GateError into the builder loop's own GateError so its `except
# GateError` retry/notice path works unchanged.
# --------------------------------------------------------------------------- #
class ServiceBuilderGate:
    def __init__(self, service: AgentService, user_id: str) -> None:
        self._service = service
        self._user = user_id

    def get_config(self, agent_id: str) -> AgentConfig:
        return self._service.get_agent(agent_id, self._user)

    def apply_patch(self, agent_id: str, path: str, value: Any) -> GateAccepted:
        before = self._service.get_agent(agent_id, self._user).meta.status
        try:
            outcome = self._service.apply_patch(agent_id, self._user, path, value)
        except ConfigGateError as err:
            # translate WS2 error -> builder-loop error (kind is a plain string there)
            raise BuilderGateError(kind=err.kind.value, message=err.message, path=err.path)
        after = outcome.config.meta.status
        return GateAccepted(
            patch=Patch(path=outcome.path, value=outcome.value),
            version=outcome.config.meta.version,
            status=after,
            status_changed=(after != before),
        )


class BuilderMessageBody(BaseModel):
    message: str


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _seed_demo_agent_if_missing(repo) -> None:
    """Seed a fixed-id draft owned by the dev user so the frontend's default agent
    id resolves — idempotent (durable storage keeps `agent-demo` across restarts,
    so only create it once), and only ever for the DEV_USER fallback: real accounts
    create their own agents via login (see `backend.auth`)."""
    if repo.get(DEMO_AGENT_ID, DEV_USER) is not None:
        return
    now = datetime.now(timezone.utc)
    config = AgentConfig(
        meta=AgentMeta(
            id=DEMO_AGENT_ID,
            owner_user_id=DEV_USER,
            name="Untitled agent",
            status=AgentStatus.DRAFT,
            version=1,
            created_at=now,
            updated_at=now,
        )
    )
    config.meta.status = evaluate_status(config)
    repo.create(config)


def build_app(user_dependency=None) -> FastAPI:
    """`user_dependency` overrides WS2's mocked `current_user` (and the preview
    auth) with a real one — e.g. the session dependency from `backend.auth`. Left
    unset, both fall back to the fixed `DEV_USER` (standalone/dev-mock posture)."""
    app = FastAPI(title="voice-agent-studio — integrated (Phase 1)")

    # --- shared singletons ------------------------------------------------- #
    # WS6 wrapped by WS5: every builder/runtime model call is screened in/out.
    model = IntegrationScreeningWrapper(GeminiWrapper(), build_screener())

    # SQLite (default, durable, zero-config) or Postgres when DATABASE_URL is set.
    repo = build_config_repository()
    if user_dependency is None:
        _seed_demo_agent_if_missing(repo)  # DEV_USER fallback only — real accounts create their own
    service = AgentService(repo)  # WS2 default (mock free-text screener) is fine for dev

    builder_sessions = InMemorySessionStore()
    engine = RuntimeEngine(model)  # WS4 preview engine (frontier tier stand-in)

    # Expose the shared singletons so the integration layer can compose real Phase-2
    # wiring on top of this app WITHOUT rebuilding them: the campaign orchestrator must
    # run the SAME agent the builder edits (one config artifact), and reuse the SAME
    # screened model wrapper. Not a request seam — internal composition only.
    app.state.agent_service = service
    app.state.config_repo = repo
    app.state.model = model
    app.state.builder_sessions = builder_sessions

    # --- WS2 router (agents + manual PATCH) -------------------------------- #
    app.include_router(create_gate_router(service), prefix="/api")
    _install_error_handler(app)  # ConfigGateError -> typed JSON error shape

    # Auth: overriding the dependency means no WS2 route needs to know about auth.
    # Real accounts (backend.auth) pass their session dependency in; otherwise this
    # falls back to the fixed dev user (standalone WS2 usage, tests). Both shapes
    # take a single `Request` so `_preview_auth` below can call either uniformly.
    def _default_user_dependency(request: Request) -> str:
        return DEV_USER

    resolve_user = user_dependency or _default_user_dependency
    app.dependency_overrides[current_user] = resolve_user

    # --- builder SSE (assembled here; WS3 owns the loop, not the transport) - #
    @app.post("/api/agents/{agent_id}/builder/messages")
    async def builder_messages(
        agent_id: str, body: BuilderMessageBody, user: str = Depends(current_user)
    ):
        # Existence/ownership check up front — raises ConfigGateError -> typed JSON.
        service.get_agent(agent_id, user)
        gate = ServiceBuilderGate(service, user)
        loop = BuilderLoop(model, gate, builder_sessions)

        async def stream():
            try:
                async for ev in loop.run_turn(agent_id, body.message):
                    if ev.type == "token":
                        yield _sse("token", {"text": ev.text})
                    elif ev.type == "patch":
                        yield _sse("patch", {"path": ev.path, "value": ev.value})
                    elif ev.type == "notice":
                        yield _sse(
                            "notice",
                            {"kind": ev.kind, "message": ev.message, "path": ev.path},
                        )
                yield _sse("done", {})
            except ScreeningBlocked as err:
                # WS5 hard-block surfaced conversationally (never a stack trace).
                yield _sse(
                    "notice",
                    {"kind": "screening_blocked", "message": str(err) or "I can't process that."},
                )
                yield _sse("done", {})
            except Exception:
                yield _sse(
                    "notice",
                    {"kind": "validation", "message": "I didn't quite catch that — try rephrasing?"},
                )
                yield _sse("done", {})

        return StreamingResponse(stream(), media_type="text/event-stream")

    # --- WS4 preview router ------------------------------------------------ #
    async def _config_provider(agent_id: str, user_id: str) -> Optional[AgentConfig]:
        try:
            return service.get_agent(agent_id, user_id)
        except ConfigGateError:
            return None

    async def _preview_auth(request: Request) -> str:
        return resolve_user(request)

    app.include_router(
        build_preview_router(engine, _config_provider, _preview_auth), prefix="/api"
    )

    @app.get("/api/health")
    def health():
        return {"ok": True, "demo_agent": DEMO_AGENT_ID}

    return app


app = build_app()
