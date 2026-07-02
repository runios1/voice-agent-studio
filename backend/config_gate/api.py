"""Thin FastAPI router for the agent + config-gate endpoints (api_contract.md).

WS2 owns exactly the endpoints that read/mutate the config artifact:

  POST   /agents                      create a draft (platform layer seeded)
  GET    /agents                      list the user's agents (meta only)
  GET    /agents/{id}                 full AgentConfig + resolved FIELD_POLICY
  PATCH  /agents/{id}/fields          the manual-edit door — SAME gate as builder
  GET    /agents/{id}/history         version list
  POST   /agents/{id}/revert/{version} undo to a prior version

It does NOT own /builder/messages or /preview/messages (WS3 / WS4). The router is
deliberately thin: all logic lives in AgentService/ConfigGate; here we only bind
HTTP, resolve the authed user, and translate GateError -> the contract error shape.

AUTH IS MOCKED: `current_user` reads an `X-User-Id` header. Replace with the real
session dependency from the auth workstream at integration — tenant scoping itself
is already enforced in code by the repository, so only the id *source* changes.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, FastAPI, Header, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from contracts.config_schema.field_policy import FIELD_POLICY
from backend.config_gate.errors import ErrorKind, GateError
from backend.config_gate.repository import ConfigRepository, InMemoryConfigRepository
from backend.config_gate.service import AgentService


# --- request bodies ----------------------------------------------------------
class CreateAgentBody(BaseModel):
    name: Optional[str] = None


class PatchFieldBody(BaseModel):
    # api_contract body is {path, value}; expected_version is an OPTIONAL extension
    # for optimistic concurrency (omit => last-write-wins). Contract stays honored.
    path: str
    value: Any = None
    expected_version: Optional[int] = None


# --- auth (MOCK) -------------------------------------------------------------
def current_user(x_user_id: Optional[str] = Header(default=None)) -> str:
    if not x_user_id:
        # Never trust a missing identity; a real session dep raises 401 here.
        raise GateError(ErrorKind.NOT_FOUND, "Not authenticated.", None)
    return x_user_id


_FIELD_POLICY_JSON = [p.model_dump(mode="json") for p in FIELD_POLICY]


def create_router(service: AgentService) -> APIRouter:
    router = APIRouter()

    @router.post("/agents")
    def create_agent(body: CreateAgentBody, user: str = Depends(current_user)):
        config = service.create_agent(user, body.name)
        return config.model_dump(mode="json")

    @router.get("/agents")
    def list_agents(user: str = Depends(current_user)):
        return [m.model_dump(mode="json") for m in service.list_agents(user)]

    @router.get("/agents/{agent_id}")
    def get_agent(agent_id: str, user: str = Depends(current_user)):
        config = service.get_agent(agent_id, user)
        # Resolved FIELD_POLICY travels with the config so the panel renders lock
        # badges + editability without a second call (api_contract).
        return {"config": config.model_dump(mode="json"), "field_policy": _FIELD_POLICY_JSON}

    @router.patch("/agents/{agent_id}/fields")
    def patch_field(agent_id: str, body: PatchFieldBody, user: str = Depends(current_user)):
        outcome = service.apply_patch(
            agent_id, user, body.path, body.value, body.expected_version
        )
        result = {
            "patch": {"path": outcome.path, "value": outcome.value},
            "config": outcome.config.model_dump(mode="json"),
            "status": outcome.config.meta.status.value,
            "version": outcome.config.meta.version,
        }
        if outcome.flag is not None:
            # Accepted-but-flagged: surface as a conversational notice, HTTP 200.
            result["notice"] = {
                "kind": outcome.flag.kind,
                "path": outcome.flag.path,
                "message": outcome.flag.message,
            }
        return result

    @router.get("/agents/{agent_id}/history")
    def history(agent_id: str, user: str = Depends(current_user)):
        return [
            {
                "version": v.version,
                "status": v.config.meta.status.value,
                "created_at": v.created_at.isoformat(),
            }
            for v in service.history(agent_id, user)
        ]

    @router.post("/agents/{agent_id}/revert/{version}")
    def revert(agent_id: str, version: int, user: str = Depends(current_user)):
        config = service.revert(agent_id, user, version)
        return config.model_dump(mode="json")

    return router


def _install_error_handler(app: FastAPI) -> None:
    @app.exception_handler(GateError)
    async def _handle_gate_error(_request, exc: GateError):
        return JSONResponse(status_code=exc.http_status, content=exc.to_dict())


def create_app(repository: Optional[ConfigRepository] = None) -> FastAPI:
    """App factory. Defaults to the in-memory repo; inject Postgres in production."""
    app = FastAPI(title="voice-agent-studio — config gate")
    service = AgentService(repository or InMemoryConfigRepository())
    app.include_router(create_router(service))
    _install_error_handler(app)
    return app
