"""AgentService — gate + persistence orchestration.

The application-facing surface WS2 owns. It wires the pure `ConfigGate` to a
`ConfigRepository`, and is where source-agnosticism actually pays off: builder
patches (later, via the builder loop) and manual PATCHes (via the API router)
both call `apply_patch` here, hitting the identical gate. Nothing bypasses it.

Every method takes the AUTHED `owner_user_id` and passes it to the repository,
which scopes in code — the service never trusts a client to say who it is.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from contracts.config_schema.schema import (
    AgentConfig,
    AgentMeta,
    AgentStatus,
)
from backend.config_gate.completeness import evaluate_status, missing_required
from backend.config_gate.errors import ErrorKind, GateError
from backend.config_gate.gate import ConfigGate, GateOutcome
from backend.config_gate.repository import ConfigRepository, NotFoundError, StoredVersion
from backend.config_gate.screening import MockScreeningAdapter, ScreeningPort


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AgentService:
    def __init__(
        self,
        repository: ConfigRepository,
        screener: Optional[ScreeningPort] = None,
    ):
        # Default to the mock screener so the service is usable before WS5 merges;
        # inject the real WS5 adapter in production — no other change required.
        self._repo = repository
        self._gate = ConfigGate(screener or MockScreeningAdapter())

    # --- creation ------------------------------------------------------------
    def create_agent(self, owner_user_id: str, name: Optional[str] = None) -> AgentConfig:
        """A fresh draft, seeded with the platform layer (locked guardrails +
        defaults come from the schema's own defaults). Version 1, status DRAFT."""
        now = _now()
        meta = AgentMeta(
            id=str(uuid.uuid4()),
            owner_user_id=owner_user_id,
            name=name or "Untitled agent",
            status=AgentStatus.DRAFT,
            version=1,
            created_at=now,
            updated_at=now,
        )
        config = AgentConfig(meta=meta)  # guardrails/conversation/automation = schema defaults
        config.meta.status = evaluate_status(config)
        return self._repo.create(config)

    # --- reads ---------------------------------------------------------------
    def get_agent(self, agent_id: str, owner_user_id: str) -> AgentConfig:
        config = self._repo.get(agent_id, owner_user_id)
        if config is None:
            raise NotFoundError(agent_id)
        return config

    def list_agents(self, owner_user_id: str) -> list[AgentMeta]:
        return self._repo.list_meta(owner_user_id)

    def history(self, agent_id: str, owner_user_id: str) -> list[StoredVersion]:
        # A tenant miss yields an empty chain from the repo; make it explicit.
        if self._repo.get(agent_id, owner_user_id) is None:
            raise NotFoundError(agent_id)
        return self._repo.list_versions(agent_id, owner_user_id)

    def missing_for_ready(self, agent_id: str, owner_user_id: str) -> list[str]:
        return missing_required(self.get_agent(agent_id, owner_user_id))

    # --- the one mutation door (builder patch OR manual edit) ----------------
    def apply_patch(
        self,
        agent_id: str,
        owner_user_id: str,
        path: str,
        value: Any,
        expected_version: Optional[int] = None,
    ) -> GateOutcome:
        """Run the gate on {path, value}; persist iff accepted. Raises GateError
        (locked_path / validation / screening_blocked / conflict / not_found) on
        rejection — never a stack trace."""
        config = self.get_agent(agent_id, owner_user_id)  # NotFound if not owned
        outcome = self._gate.check_and_apply(config, path, value)  # may raise GateError
        saved = self._repo.save(outcome.config, owner_user_id, expected_version)
        return GateOutcome(config=saved, path=outcome.path, value=outcome.value, flag=outcome.flag)

    # --- undo ----------------------------------------------------------------
    def revert(self, agent_id: str, owner_user_id: str, version: int) -> AgentConfig:
        """Restore a prior snapshot as a NEW version (history stays append-only)."""
        snapshot = self._repo.get_version(agent_id, owner_user_id, version)
        if snapshot is None:
            # Distinguish "no such agent" from "no such version" for a better message.
            if self._repo.get(agent_id, owner_user_id) is None:
                raise NotFoundError(agent_id)
            raise GateError(ErrorKind.NOT_FOUND, f"No version {version} for this agent.", agent_id)
        snapshot.meta.status = evaluate_status(snapshot)
        return self._repo.save(snapshot, owner_user_id)
