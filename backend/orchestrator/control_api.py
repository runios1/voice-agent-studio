"""Thin FastAPI control surface for the dashboard (P2-7) and the auto-pause hook (P2-6).

Deliberately thin — same posture as config_gate's router: all logic is in
`OrchestratorService`; here we only bind HTTP, resolve the authed user, and translate
`OrchestratorError -> {error: {...}}`. Tenant scoping is enforced in the service/repo
(in code), so a campaign that isn't yours is a 404, never leaked (D-security).

  POST /campaigns                      authorize a campaign (P2-D1)
  GET  /campaigns                      list the user's campaigns
  GET  /campaigns/{id}                 one campaign (state + autopause_reason)
  GET  /campaigns/{id}/leads           per-lead state (dashboard drill-down)
  POST /campaigns/{id}/pause           manual kill switch
  POST /campaigns/{id}/resume          un-pause
  POST /campaigns/{id}/autopause       the hook P2-6 calls (body: {reason})
  POST /emergency-stop                 global stop for the tenant
  POST /emergency-stop/clear           lift the global stop

AUTH IS MOCKED: `current_user` reads `X-User-Id` (same convention as config_gate).
Running the dispatch loop itself (`run_campaign`) is a worker/background concern, not
an HTTP call, so it is intentionally NOT exposed here.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from contracts.campaign.model import GuardrailEnvelope
from backend.orchestrator.errors import ErrorKind, OrchestratorError
from backend.orchestrator.service import LeadSpec, OrchestratorService


class AuthorizeBody(BaseModel):
    agent_id: str
    leads: list[LeadSpec]
    envelope: Optional[GuardrailEnvelope] = None
    name: str = "Untitled campaign"


class AutopauseBody(BaseModel):
    reason: str


def current_user(x_user_id: Optional[str] = Header(default=None)) -> str:
    if not x_user_id:
        raise OrchestratorError(ErrorKind.NOT_FOUND, "Not authenticated.", None)
    return x_user_id


def create_router(service: OrchestratorService) -> APIRouter:
    router = APIRouter()

    @router.post("/campaigns")
    async def authorize(body: AuthorizeBody, user: str = Depends(current_user)):
        campaign = await service.authorize_campaign(
            tenant_id=user,
            agent_id=body.agent_id,
            authorized_by=user,
            leads=body.leads,
            envelope=body.envelope,
            name=body.name,
        )
        return campaign.model_dump(mode="json")

    @router.get("/campaigns")
    def list_campaigns(user: str = Depends(current_user)):
        return [c.model_dump(mode="json") for c in service.list_campaigns(user)]

    @router.get("/campaigns/{campaign_id}")
    def get_campaign(campaign_id: str, user: str = Depends(current_user)):
        return service.get_campaign(campaign_id, user).model_dump(mode="json")

    @router.get("/campaigns/{campaign_id}/leads")
    def list_leads(campaign_id: str, user: str = Depends(current_user)):
        return [l.model_dump(mode="json") for l in service.list_leads(campaign_id, user)]

    @router.post("/campaigns/{campaign_id}/pause")
    async def pause(campaign_id: str, user: str = Depends(current_user)):
        return (await service.pause(campaign_id, user)).model_dump(mode="json")

    @router.post("/campaigns/{campaign_id}/resume")
    async def resume(campaign_id: str, user: str = Depends(current_user)):
        return (await service.resume(campaign_id, user)).model_dump(mode="json")

    @router.post("/campaigns/{campaign_id}/autopause")
    async def autopause(campaign_id: str, body: AutopauseBody, user: str = Depends(current_user)):
        return (await service.autopause(campaign_id, user, body.reason)).model_dump(mode="json")

    @router.post("/emergency-stop")
    async def emergency_stop(user: str = Depends(current_user)):
        await service.emergency_stop(user)
        return {"stopped": True}

    @router.post("/emergency-stop/clear")
    async def clear_emergency_stop(user: str = Depends(current_user)):
        service.clear_emergency_stop(user)
        return {"stopped": False}

    return router


def _install_error_handler(app: FastAPI) -> None:
    @app.exception_handler(OrchestratorError)
    async def _handle(_request, exc: OrchestratorError):
        return JSONResponse(status_code=exc.http_status, content=exc.to_dict())


def create_app(service: OrchestratorService) -> FastAPI:
    app = FastAPI(title="voice-agent-studio — campaign orchestrator")
    app.include_router(create_router(service))
    _install_error_handler(app)
    return app
