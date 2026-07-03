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

import asyncio
from contextlib import suppress
from typing import Optional

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
from backend.orchestrator.mocks import ScriptedDialer
from backend.orchestrator.service import OrchestratorService
from backend.phase2_app import (
    DEV_USER,
    EventServiceSink,
    _DefaultConfigSource,
    _inline_seed,
    _resolve_seed_and_run,
)


def build_app() -> FastAPI:
    # Base = the Phase-1 studio app (its routes, seeded demo agent, config-gate error
    # handler, and current_user override are already installed inside build_studio_app).
    app = build_studio_app()

    # --- Phase-2: the one shared event log, threaded as the orchestrator's sink ---- #
    events = EventService()
    orch = OrchestratorService(
        config_source=_DefaultConfigSource(),
        dialer=ScriptedDialer(),
        sink=EventServiceSink(events),
    )
    app.state.events = events
    app.state.orch = orch

    app.include_router(create_orch_router(orch), prefix="/api")
    app.include_router(create_events_router(events), prefix="/api")
    install_orch_error_handler(app)
    install_events_error_handler(app)

    # Phase-2 dev auth: same fixed identity as Phase-1 (user == tenant == "dev-user"),
    # so the dashboard's tenant sees the seeded campaigns/events.
    app.dependency_overrides[current_user] = lambda: DEV_USER
    app.dependency_overrides[current_tenant] = lambda: DEV_USER

    # SEED (contract §4b.5): prefer INT-C's live demo motion; else a minimal inline seed.
    # The base app has no lifespan we can extend, so drive the seed from startup/shutdown.
    demo: dict[str, Optional[object]] = {"stop": None, "task": None}

    @app.on_event("startup")
    async def _seed_phase2() -> None:
        seed = _resolve_seed_and_run()
        stop = asyncio.Event()
        demo["stop"] = stop
        if seed is not None:
            demo["task"] = asyncio.create_task(seed(orch, events, tenant=DEV_USER, stop=stop))
        else:
            await _inline_seed(orch)

    @app.on_event("shutdown")
    async def _stop_phase2() -> None:
        stop = demo.get("stop")
        if isinstance(stop, asyncio.Event):
            stop.set()
        task = demo.get("task")
        if isinstance(task, asyncio.Task):
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task

    return app


app = build_app()
