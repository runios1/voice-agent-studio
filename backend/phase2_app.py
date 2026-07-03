"""Phase-2 integration assembly — the ONE FastAPI app that wires the Phase-2 backend.

The Phase-2 workstreams (orchestrator P2-2, event backbone P2-5, dashboard P2-7, …)
were merged mostly-mocked and in parallel; each shipped a module but none owns the
process that binds them into the routes the dashboard calls. That wiring lives here,
and ONLY here. This is the backend half of the frozen contract
`contracts/dashboard_http/README.md` (INT-A).

The keystone (contract §4): build **one** `EventService` and thread it EVERYWHERE as
the orchestrator's sink, so a control action (pause) and a produced call event land in
the SAME append-only log the dashboard reads. That is what makes reflection
server-authoritative — the dashboard flips a campaign's state when the `campaign.*`
event arrives on the stream, not on the click.

Composition:

    EventService (P2-5)                         # one durable log + live bus
      └─ EventServiceSink                       # adapts it to the orchestrator's EventSink
           └─ OrchestratorService (P2-2)        # emits campaign.* through that sink

Routes (all under /api so the Vite dev proxy forwards /api -> :8000 unchanged):

    GET/POST  /api/campaigns ...                orchestrator control API (P2-2)
    POST      /api/campaigns/{id}/pause|resume  kill switch
    POST      /api/emergency-stop               tenant-global stop
    GET       /api/events                       audit query  (rows: {seq, event})
    GET       /api/events/stream                live SSE tail
    GET       /api/events/export                NDJSON compliance export
    GET       /api/health                       {"ok": true}

Phase-2 shortcuts (dev-only, swapped at real integration, per contract §0):
  * AUTH is a fixed dev user where user == tenant ("dev-user"): both auth dependencies
    (`control_api.current_user` and `events.router.current_tenant`) are overridden, so
    the frontend sends NO auth headers. Real session auth drops in without a route or
    client change.
  * The `ConfigSource` is a stub returning a default platform-guardrailed AgentConfig
    (the orchestrator only needs the LOCKED guardrails to clamp the envelope), and the
    dialer is a mock — the dashboard E2E does not place real dials.
  * SEED: on startup we call INT-C's `seed_and_run(orch, events, ...)` if it is present
    (live demo motion), otherwise fall back to a minimal inline seed (one authorized
    campaign) so the fleet is non-empty. INT-A MUST boot without INT-C.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from fastapi import FastAPI

from contracts.config_schema.schema import AgentConfig, AgentMeta, AgentStatus
from contracts.events.schema import Event

# P2-5 — event backbone
from backend.events.router import (
    create_router as create_events_router,
    current_tenant,
    install_error_handler as install_events_error_handler,
)
from backend.events.service import EventService

# P2-2 — campaign orchestrator
from backend.orchestrator.control_api import (
    _install_error_handler as install_orch_error_handler,
    create_router as create_orch_router,
    current_user,
)
from backend.orchestrator.mocks import ScriptedDialer
from backend.orchestrator.service import LeadSpec, OrchestratorService


DEV_USER = "dev-user"  # user == tenant in v1 (contract §0)
DEMO_AGENT_ID = "agent-demo"

# Frozen signature INT-C implements and INT-A calls (contract §4c).
SeedAndRun = Callable[..., Awaitable[None]]


# --------------------------------------------------------------------------- #
# EventSink adapter (contract §4a).
# The orchestrator depends on a tiny `EventSink.emit(event: Event)`; P2-5's
# `EventService.emit` takes a type + kwargs and validates/persists/publishes. This
# adapter is the join: one control action and one produced call event flow into the
# same log. `EventService.emit` validates the payload per type — a producer payload
# that fails validation is a real integration bug to fix in the producer, not to
# silence here (contract §4a).
# --------------------------------------------------------------------------- #
class EventServiceSink:
    """Adapts P2-5 `EventService` to the orchestrator's `EventSink` protocol."""

    def __init__(self, service: EventService) -> None:
        self._svc = service

    async def emit(self, event: Event) -> None:
        await self._svc.emit(
            event.type,
            tenant_id=event.tenant_id,
            payload=event.payload,
            severity=event.severity,
            campaign_id=event.campaign_id,
            lead_id=event.lead_id,
            call_id=event.call_id,
            agent_id=event.agent_id,
            event_id=event.event_id,
            occurred_at=event.occurred_at,
        )


# --------------------------------------------------------------------------- #
# Stub ConfigSource (contract §4b.2).
# The orchestrator only reads the LOCKED guardrails to clamp the authorized envelope
# (D4/D-security), so a default schema config for any agent is sufficient in dev. It
# returns a config for ANY agent id so both the inline seed and INT-C's own
# authorize (which may pick arbitrary ids) resolve.
# --------------------------------------------------------------------------- #
class _DefaultConfigSource:
    def get_config(self, agent_id: str, tenant_id: str) -> Optional[AgentConfig]:
        now = datetime.now(timezone.utc)
        return AgentConfig(
            meta=AgentMeta(
                id=agent_id,
                owner_user_id=tenant_id,
                name="Demo agent",
                status=AgentStatus.DRAFT,
                version=1,
                created_at=now,
                updated_at=now,
            )
        )


def _resolve_seed_and_run() -> Optional[SeedAndRun]:
    """Return INT-C's `seed_and_run` if the demo module is present, else None.

    Only a MISSING module falls back to the inline seed (graceful — INT-A must run
    without INT-C). A module that exists but fails to import is an INT-C bug that must
    surface loudly, so it is NOT swallowed here."""
    try:
        from backend.phase2_demo import seed_and_run  # type: ignore
    except ImportError:
        return None
    return seed_and_run


async def _inline_seed(orch: OrchestratorService) -> None:
    """Minimal fallback seed: authorize one running campaign with a few leads so the
    fleet is non-empty. Emits `campaign.started` through the shared sink, so even the
    fallback puts a real row on the audit log."""
    await orch.authorize_campaign(
        tenant_id=DEV_USER,
        agent_id=DEMO_AGENT_ID,
        authorized_by=DEV_USER,
        leads=[
            LeadSpec(phone="+15550100", display_name="Ada Lovelace"),
            LeadSpec(phone="+15550101", display_name="Alan Turing"),
            LeadSpec(phone="+15550102", display_name="Grace Hopper"),
        ],
        name="Demo outbound — Q3 SDR",
    )


def build_app() -> FastAPI:
    # --- the ONE event log, threaded everywhere as the orchestrator's sink ------ #
    events = EventService()
    orch = OrchestratorService(
        config_source=_DefaultConfigSource(),
        dialer=ScriptedDialer(),          # mock — the dashboard E2E places no real dials
        sink=EventServiceSink(events),    # <- the keystone join (contract §4)
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # SEED (contract §4b.5): prefer INT-C's live demo; else a minimal inline seed.
        seed = _resolve_seed_and_run()
        stop = asyncio.Event()
        task: Optional[asyncio.Task] = None
        if seed is not None:
            task = asyncio.create_task(seed(orch, events, tenant=DEV_USER, stop=stop))
        else:
            await _inline_seed(orch)
        app.state.demo_stop = stop
        app.state.demo_task = task
        try:
            yield
        finally:
            stop.set()
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task

    app = FastAPI(title="voice-agent-studio — Phase 2 (integrated)", lifespan=lifespan)
    # Expose the shared instances for tests/JOIN drivers (not a request seam).
    app.state.events = events
    app.state.orch = orch

    # --- mount both routers under /api, install both typed-error handlers ------- #
    app.include_router(create_orch_router(orch), prefix="/api")
    app.include_router(create_events_router(events), prefix="/api")
    install_orch_error_handler(app)
    install_events_error_handler(app)

    # --- Phase-2 auth: fixed dev user, user == tenant (contract §0) ------------- #
    # Overriding both deps means no route knows about auth and the frontend sends no
    # auth headers; tenant scoping itself is already enforced in each module's code.
    app.dependency_overrides[current_user] = lambda: DEV_USER
    app.dependency_overrides[current_tenant] = lambda: DEV_USER

    @app.get("/api/health")
    def health():
        return {"ok": True}

    return app


app = build_app()
