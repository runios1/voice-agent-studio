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
import os

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
from backend.tool_registry.connections_router import (
    create_router as create_connections_router,
    current_tenant as connections_current_tenant,
    install_error_handler as install_connections_error_handler,
)

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
from backend.live_agent.compiler import LiveAgentCompilerImpl
from backend.live_agent.moderation import build_stream_moderator
from backend.live_agent.preview_transport import create_router as create_live_preview_router
from backend.live_agent.phone_transport import create_twilio_media_router, twilio_configured
from backend.live_agent.session import GeminiLiveAgentSession
from backend.integration.live_dialer import build_live_dialer
from backend.security import build_screener

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
    config_source = AgentServiceConfigSource(service)
    # Phone dialing: when Twilio is configured, campaign calls run the SAME Live-native
    # agent as the browser preview over a real phone (LiveDialer + Twilio Media Streams).
    # Without Twilio, fall back to the scripted-mock text dialer so a campaign still runs
    # end-to-end in dev.
    if twilio_configured():
        dialer = build_live_dialer(tool_stack, sink)
    else:
        dialer = RealDialer(engine, tool_stack, make_transport_factory(), sink)
    orch = SupervisedOrchestrator(
        config_source=config_source,
        dialer=dialer,
        repo=build_orchestrator_repository(),  # Postgres per-lead state when configured
        sink=sink,
    )
    app.state.events = events
    app.state.orch = orch
    app.state.tool_stack = tool_stack

    # Backend's own OAuth callback URL (must match what's registered with the
    # provider) vs. where the browser bounces back to in the app once it's run.
    oauth_redirect_base = os.getenv("OAUTH_REDIRECT_BASE_URL", "http://localhost:8000")
    app_base_url = os.getenv("APP_BASE_URL", "http://localhost:5173")

    app.include_router(create_orch_router(orch), prefix="/api")
    app.include_router(create_events_router(events), prefix="/api")
    app.include_router(
        create_connections_router(
            tool_stack.connection_manager,
            tool_stack.connections,
            redirect_uri=f"{oauth_redirect_base}/api/oauth/callback",
            app_redirect_url=app_base_url,
        ),
        prefix="/api",
    )
    # P4-6 — live talking preview, Live-native (Phase 4 pivot): Gemini Live IS the
    # agent (audio-to-audio), driven by the compiled LiveAgentSpec + the per-agent
    # tool registry a real call uses, with output-transcription moderation as a net.
    # Replaces the P3-4 STT+TTS bridge on the SAME WS route
    # /api/agents/{id}/preview/voice. The compiler and screener are shared
    # singletons; a fresh Live session + moderator are minted per connection (both
    # carry per-call state), mirroring the CallEngine posture.
    screener = build_screener()
    app.include_router(
        create_live_preview_router(
            config_source,
            tool_stack,
            LiveAgentCompilerImpl(),
            sink,
            session_factory=lambda: GeminiLiveAgentSession(sink),
            moderator_factory=lambda: build_stream_moderator(screener),
        ),
        prefix="/api",
    )
    # Twilio Media Streams endpoint for real phone calls (the LiveDialer's phone leg).
    # Mounted at the ROOT (no /api prefix): Twilio's <Stream> dials
    # wss://{PUBLIC_WSS_BASE}/twilio/media/{token}, which build_phone_transport builds
    # to match. Harmless (an unrecognized token is closed) when Twilio isn't configured.
    app.include_router(create_twilio_media_router())
    install_orch_error_handler(app)
    install_events_error_handler(app)
    install_connections_error_handler(app)

    # Phase-2 dev auth: same fixed identity as Phase-1 (user == tenant == "dev-user"),
    # so the dashboard's tenant sees the seeded campaigns/events.
    app.dependency_overrides[current_user] = lambda: DEV_USER
    app.dependency_overrides[current_tenant] = lambda: DEV_USER
    app.dependency_overrides[connections_current_tenant] = lambda: DEV_USER

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
