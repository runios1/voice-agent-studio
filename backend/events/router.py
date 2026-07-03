"""Thin FastAPI router over the event backbone — the surface P2-7 (dashboard) mounts.

Same split config_gate used: the router only binds HTTP, resolves the authed tenant,
and translates typed errors; all logic lives in `EventService` / `analytics`. The
integrator wires this into the one app (auth dep, real store) — this module owns no
process wiring.

Endpoints (all tenant-scoped in code — never by a client-supplied id, D-security):

  GET  /events                  audit query (filter by type/severity/correlation/time)
  GET  /events/export           same filter -> NDJSON download (compliance hand-off)
  GET  /events/analytics        roll-ups (counts, outcomes, guardrail trips)
  GET  /events/analytics/series time-bucketed counts (sparklines)
  GET  /events/stream           live SSE tail (D10: SSE), with after_seq backfill

LIVE STREAM — no-gap guarantee: the stream first REPLAYS from the durable store
(everything after `after_seq`) then attaches the live bus tail. Because the store
assigns the monotonic seq and the bus publishes post-persist, a subscriber that
passes the last seq it saw can never miss nor need to dedupe an event across the
backfill/live seam.

AUTH IS MOCKED here exactly like config_gate: `current_tenant` reads `X-Tenant-Id`.
The integrator overrides it with the real session dep; tenant scoping itself is
already enforced in code, so only the id *source* changes.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import AsyncIterator, Awaitable, Callable, Optional

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from contracts.events.schema import EventType, Severity
from backend.events.analytics import aggregate, time_series
from backend.events.errors import EventError
from backend.events.service import EventService
from backend.events.store import EventQuery, StoredEvent


def current_tenant(x_tenant_id: Optional[str] = Header(default=None)) -> str:
    if not x_tenant_id:
        raise EventError("Not authenticated.")  # real session dep raises 401 here
    return x_tenant_id


def _build_query(
    tenant_id: str,
    *,
    type: Optional[list[str]] = None,
    severity: Optional[list[str]] = None,
    campaign_id: Optional[str] = None,
    lead_id: Optional[str] = None,
    call_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    after_seq: Optional[int] = None,
    limit: Optional[int] = None,
) -> EventQuery:
    return EventQuery(
        tenant_id=tenant_id,
        types=frozenset(EventType(t) for t in type) if type else None,
        severities=frozenset(Severity(s) for s in severity) if severity else None,
        campaign_id=campaign_id,
        lead_id=lead_id,
        call_id=call_id,
        agent_id=agent_id,
        since=since,
        until=until,
        after_seq=after_seq,
        limit=limit,
    )


def _row(s: StoredEvent) -> dict:
    return {"seq": s.seq, "event": s.event.model_dump(mode="json")}


def _sse(data: dict) -> str:
    # SSE frame; `id:` carries seq so a reconnecting client resumes via Last-Event-ID.
    return f"id: {data['seq']}\nevent: event\ndata: {json.dumps(data)}\n\n"


async def event_sse_stream(
    service: EventService,
    q: EventQuery,
    is_disconnected: Callable[[], Awaitable[bool]],
    *,
    heartbeat_seconds: float = 15.0,
) -> AsyncIterator[str]:
    """The SSE body: backfill then live tail, with a no-gap / no-dupe guarantee.

    Extracted from the route so it is unit-testable without an HTTP transport (httpx's
    ASGITransport buffers whole responses, so it cannot drive an infinite stream).

    NO-GAP: subscribe to the live bus BEFORE reading the backfill, so an event that
    arrives mid-backfill is captured by the subscription rather than lost in the seam.
    NO-DUPE: the small overlap (an event in both backfill and live tail) is dropped by
    the `seq <= backfilled_to` check. `is_disconnected` is polled on each idle tick so
    a gone client tears the stream down instead of leaking a subscription."""
    after_seq = q.after_seq or 0
    sub = service.subscribe(q)
    try:
        backfilled_to = after_seq
        for s in service.query(q):
            backfilled_to = max(backfilled_to, s.seq)
            yield _sse(_row(s))
        while True:
            try:
                s = await sub.get(timeout=heartbeat_seconds)
            except asyncio.TimeoutError:
                if await is_disconnected():
                    break
                yield ": keepalive\n\n"  # SSE comment; keeps the pipe warm
                continue
            if s is None:  # subscription closed
                break
            if s.seq <= backfilled_to:
                continue  # already sent in backfill — no dupe
            if await is_disconnected():
                break
            yield _sse(_row(s))
    finally:
        sub.close()


def create_router(service: EventService) -> APIRouter:
    router = APIRouter()

    @router.get("/events")
    def query_events(
        tenant: str = Depends(current_tenant),
        type: Optional[list[str]] = Query(default=None),
        severity: Optional[list[str]] = Query(default=None),
        campaign_id: Optional[str] = Query(default=None),
        lead_id: Optional[str] = Query(default=None),
        call_id: Optional[str] = Query(default=None),
        agent_id: Optional[str] = Query(default=None),
        since: Optional[datetime] = Query(default=None),
        until: Optional[datetime] = Query(default=None),
        after_seq: Optional[int] = Query(default=None),
        limit: Optional[int] = Query(default=None),
    ):
        q = _build_query(
            tenant, type=type, severity=severity, campaign_id=campaign_id,
            lead_id=lead_id, call_id=call_id, agent_id=agent_id, since=since,
            until=until, after_seq=after_seq, limit=limit,
        )
        return [_row(s) for s in service.query(q)]

    @router.get("/events/export")
    def export_events(
        tenant: str = Depends(current_tenant),
        type: Optional[list[str]] = Query(default=None),
        severity: Optional[list[str]] = Query(default=None),
        campaign_id: Optional[str] = Query(default=None),
        since: Optional[datetime] = Query(default=None),
        until: Optional[datetime] = Query(default=None),
    ):
        q = _build_query(
            tenant, type=type, severity=severity, campaign_id=campaign_id,
            since=since, until=until,
        )
        return PlainTextResponse(
            service.export_ndjson(q),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": 'attachment; filename="events.ndjson"'},
        )

    @router.get("/events/analytics")
    def analytics(
        tenant: str = Depends(current_tenant),
        campaign_id: Optional[str] = Query(default=None),
        since: Optional[datetime] = Query(default=None),
        until: Optional[datetime] = Query(default=None),
    ):
        q = _build_query(tenant, campaign_id=campaign_id, since=since, until=until)
        return aggregate(service._store, q).to_dict()

    @router.get("/events/analytics/series")
    def analytics_series(
        tenant: str = Depends(current_tenant),
        campaign_id: Optional[str] = Query(default=None),
        since: Optional[datetime] = Query(default=None),
        until: Optional[datetime] = Query(default=None),
        bucket_seconds: int = Query(default=3600, gt=0),
    ):
        q = _build_query(tenant, campaign_id=campaign_id, since=since, until=until)
        return [b.to_dict() for b in time_series(service._store, q, bucket_seconds=bucket_seconds)]

    @router.get("/events/stream")
    async def stream(
        request: Request,
        tenant: str = Depends(current_tenant),
        type: Optional[list[str]] = Query(default=None),
        severity: Optional[list[str]] = Query(default=None),
        campaign_id: Optional[str] = Query(default=None),
        last_event_id: Optional[int] = Query(default=None, alias="after_seq"),
    ):
        q = _build_query(
            tenant, type=type, severity=severity, campaign_id=campaign_id, after_seq=last_event_id
        )
        return StreamingResponse(
            event_sse_stream(service, q, request.is_disconnected),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router


def install_error_handler(app: FastAPI) -> None:
    @app.exception_handler(EventError)
    async def _handle(_request, exc: EventError):
        return JSONResponse(status_code=exc.http_status, content=exc.to_dict())


def create_app(service: Optional[EventService] = None) -> FastAPI:
    """Standalone app factory (dev/E2E). Production mounts `create_router` into the
    one app and injects the Postgres-backed service."""
    app = FastAPI(title="voice-agent-studio — event backbone")
    svc = service or EventService()
    app.include_router(create_router(svc))
    install_error_handler(app)
    return app
