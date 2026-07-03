"""The ONE server for a local full-stack run — Phase-1 studio + Phase-2 ops in a
single FastAPI, so BOTH frontend surfaces work against one `:8000` backend.

Why this exists: Phase-1 (`backend/app.py`) serves the builder studio routes
(`/api/agents`, builder SSE, preview SSE); Phase-2 (`backend/phase2_app.py`) serves the
ops-dashboard routes (`/api/campaigns`, `/api/events`). Each is a complete, independently
tested assembly — but neither serves the *other's* routes, so running only one 404s the
other surface. This module is a thin **composition entrypoint**: it reuses each phase's
assembly verbatim (no new business logic) and layers the Phase-2 routes onto the Phase-1
app so the frontend's `/api` proxy target answers everything.

    build_app (backend.app)            -> /api/agents, builder SSE, preview SSE, health
      + orchestrator + events routers  -> /api/campaigns, /api/events, /api/emergency-stop
      + the shared EventService sink    (so pause reflects via the stream — contract §4)

Both surfaces share the same fixed dev identity (`dev-user`, user == tenant), so the
seeded campaigns and their events are visible to the dashboard. Route namespaces are
disjoint (`/agents…` vs `/campaigns…`/`/events…`), so nothing collides; the one shared
name, `/api/health`, is kept from Phase-1.

Run:  set -a && source .env && set +a          # Phase-1 needs GEMINI_API_KEY
      python -m uvicorn backend.integrated_app:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

# Phase-1 studio assembly (agents / builder / preview), reused as the base app.
from backend.app import build_app as build_studio_app

# Phase-2 routers + the exact wiring pieces INT-A already defined — imported, not
# duplicated, so this stays a composition entrypoint.
from backend.events.router import (
    create_router as create_events_router,
    current_tenant,
    install_error_handler as install_events_error_handler,
)
from backend.events.service import EventService
from backend.orchestrator.control_api import (
    _install_error_handler as install_orch_error_handler,
    create_router as create_orch_router,
    current_user,
)
from backend.phase2_app import DEV_USER, EventServiceSink

from backend.integration.config_source import AgentServiceConfigSource
from backend.integration.dialer import RealDialer
from backend.integration.runtime import (
    build_call_engine,
    build_tool_stack,
    make_transport_factory,
    retell_configured,
)
from backend.integration.persistence import (
    build_event_service,
    build_orchestrator_repository,
)
from backend.integration.supervisor import SupervisedOrchestrator

log = logging.getLogger("voice_agent_studio.integrated")


def build_app() -> FastAPI:
    # Base = the Phase-1 studio app (its routes, seeded demo agent, config-gate error
    # handler, and current_user override are already installed inside build_studio_app).
    app = build_studio_app()
    # Reuse the studio's already-built singletons (exposed on app.state): campaigns must
    # run the SAME agent the builder edits, and reuse the SAME screened model wrapper.
    service = app.state.agent_service
    model = app.state.model

    # --- Phase-2: the one shared event log, threaded as the orchestrator's sink ---- #
    events = build_event_service()  # Postgres store+bus when DATABASE_URL is set
    sink = EventServiceSink(events)

    # Real wiring (not stubs): the campaign loads the built AgentConfig, dials over the
    # real voice CallEngine + per-agent tool registry, on a real Retell transport when
    # configured (else a scripted mock so campaigns still run end-to-end).
    tool_stack = build_tool_stack()
    engine = build_call_engine(model, sink)
    orch = SupervisedOrchestrator(
        config_source=AgentServiceConfigSource(service),
        dialer=RealDialer(engine, tool_stack, make_transport_factory(), sink),
        repo=build_orchestrator_repository(),  # Postgres per-lead state when configured
        sink=sink,
    )
    app.state.events = events
    app.state.orch = orch
    app.state.tool_stack = tool_stack

    app.include_router(create_orch_router(orch), prefix="/api")
    app.include_router(create_events_router(events), prefix="/api")
    install_orch_error_handler(app)
    install_events_error_handler(app)

    # Phase-2 dev auth: same fixed identity as Phase-1 (user == tenant == "dev-user"),
    # so the dashboard's tenant sees the seeded campaigns/events.
    app.dependency_overrides[current_user] = lambda: DEV_USER
    app.dependency_overrides[current_tenant] = lambda: DEV_USER

    @app.on_event("startup")
    async def _prime() -> None:
        # Dev: seed placeholder tool connections so the MOCK calendar/email clients run
        # before real OAuth is wired (no-op once real providers are configured). Nothing
        # auto-dials on boot — users authorize their OWN campaigns (real-product behavior).
        tool_stack.ensure_dev_connections(DEV_USER)
        log.info(
            "integrated app ready — phone transport=%s",
            "retell" if retell_configured() else "mock",
        )

    @app.on_event("shutdown")
    async def _drain() -> None:
        # Stop launching new dials and cancel in-flight campaign loops for a clean exit.
        await orch.shutdown()

    return app


app = build_app()
