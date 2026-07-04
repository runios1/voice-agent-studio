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

Both surfaces share the same real identity: whoever is signed in via Google
(`backend.auth`) is `user == tenant`, so the campaigns/events they create are the
ones the dashboard shows them. Route namespaces are disjoint (`/agents…` vs
`/campaigns…`/`/events…`), so nothing collides; the one shared name, `/api/health`,
is kept from Phase-1.

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
from backend.phase2_app import EventServiceSink
from backend.tool_registry.connections_router import (
    create_router as create_connections_router,
    current_tenant as connections_current_tenant,
    install_error_handler as install_connections_error_handler,
)

# Real accounts: Google sign-in + session cookie (replaces the fixed dev user).
from backend.auth.router import create_router as create_auth_router
from backend.auth.session import build_current_user_dependency
from backend.integration.auth_wiring import build_google_login_provider

from backend.integration.capability_sync import enable_connected_capabilities
from backend.integration.config_source import AgentServiceConfigSource
from backend.integration.dialer import RealDialer
from backend.integration.runtime import (
    build_call_engine,
    build_tool_stack,
    make_transport_factory,
    retell_configured,
)
from backend.integration.persistence import (
    build_auth_store,
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
from backend.static_site import mount_frontend

log = logging.getLogger("voice_agent_studio.integrated")

# Send our own loggers to stdout. uvicorn only configures its own loggers, leaving the
# root without a handler — so application logs (tool failures, capability sync, provider
# errors) fell through to the WARNING-only last-resort handler, which is why real errors
# were invisible in the deploy logs. Honor LOG_LEVEL (default INFO). basicConfig is a
# no-op if the root already has handlers, so it won't fight a host that configured them.
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def build_app() -> FastAPI:
    # Real accounts: one session store + one dependency, shared by every workstream's
    # mocked current_user/current_tenant below (each already enforces tenant isolation
    # in code — only the id *source* changes, exactly as each workstream anticipated).
    auth_store = build_auth_store()  # Postgres/SQLite when durable, in-memory in tests
    current_user_id = build_current_user_dependency(auth_store)

    # Base = the Phase-1 studio app (its routes, config-gate error handler, and
    # current_user override are already installed inside build_studio_app).
    app = build_studio_app(user_dependency=current_user_id)
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
    # provider) vs. where the browser bounces back to in the app once it's run. On
    # Render, both default to the service's own https URL (RENDER_EXTERNAL_URL) — a
    # single same-origin service — so a deploy needs no manual URL wiring.
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    oauth_redirect_base = os.getenv("OAUTH_REDIRECT_BASE_URL") or render_url or "http://localhost:8000"
    app_base_url = os.getenv("APP_BASE_URL") or render_url or "http://localhost:5173"

    # Capability follows connection: linking a provider (calendar/email) enables that
    # capability on the tenant's agents, so a user who connects their calendar can
    # actually book — no hidden per-agent flag to hunt for. `on_connected` handles a
    # fresh OAuth link; the login reconcile self-heals agents built before this and
    # covers the platform-level email connection (seeded at login, not via a click).
    def _sync_connected_capabilities(tenant_id: str, provider: str | None = None) -> None:
        enable_connected_capabilities(
            service, tool_stack.connections, tenant_id, provider=provider
        )

    def _on_login(tenant_id: str) -> None:
        tool_stack.ensure_dev_connections(tenant_id)
        _sync_connected_capabilities(tenant_id)

    app.include_router(create_orch_router(orch), prefix="/api")
    app.include_router(create_events_router(events), prefix="/api")
    app.include_router(
        create_connections_router(
            tool_stack.connection_manager,
            tool_stack.connections,
            redirect_uri=f"{oauth_redirect_base}/api/oauth/callback",
            app_redirect_url=app_base_url,
            on_connected=lambda tenant, provider: _sync_connected_capabilities(
                tenant, provider
            ),
        ),
        prefix="/api",
    )
    app.include_router(
        create_auth_router(
            auth_store,
            build_google_login_provider(),
            redirect_uri=f"{oauth_redirect_base}/api/auth/google/callback",
            app_redirect_url=app_base_url,
            # On login: seed placeholder tool connections (dev convenience, no-op once
            # real providers are connected) THEN enable any already-connected
            # capability on the user's agents (self-heals pre-existing agents).
            on_login=_on_login,
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

    # Real accounts: user == tenant == whoever the session cookie resolves to.
    app.dependency_overrides[current_user] = current_user_id
    app.dependency_overrides[current_tenant] = current_user_id
    app.dependency_overrides[connections_current_tenant] = current_user_id

    @app.on_event("startup")
    async def _prime() -> None:
        # Nothing auto-dials on boot — users authorize their OWN campaigns
        # (real-product behavior). Per-user dev tool-connection seeding happens at
        # login (see on_login above), not here (there's no fixed dev user anymore).
        log.info(
            "integrated app ready — phone transport=%s",
            "retell" if retell_configured() else "mock",
        )

    @app.on_event("shutdown")
    async def _drain() -> None:
        # Stop launching new dials and cancel in-flight campaign loops for a clean exit.
        await orch.shutdown()

    # Serve the built SPA same-origin (production/Docker). No-op in local dev / tests
    # where there's no frontend/dist — added LAST so /api + WS routes win over the shell.
    served = mount_frontend(app)
    log.info("frontend served from backend: %s", served)

    return app


app = build_app()
