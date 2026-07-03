"""The real orchestrator `ConfigSource` — reads the agent the user actually built.

Phase-2's `_DefaultConfigSource` returned a fresh default `AgentConfig` for ANY id, so a
campaign never ran the user's real agent (their persona, guardrails, enabled tools). The
orchestrator only needs `get_config(agent_id, tenant_id) -> Optional[AgentConfig]`, which
is exactly what the studio's `AgentService.get_agent(agent_id, owner_user_id)` already
returns — modulo the not-found convention (raise vs. None). This adapter bridges the two,
so the SAME config object the builder loop edits is the one the runtime executes (the
"one config artifact, two loops" keystone).

Tenant scoping: in dev, user == tenant, and `AgentService` already scopes reads to the
owner in code (D-security), so passing `tenant_id` as the owner is correct and safe.
"""

from __future__ import annotations

from typing import Optional

from contracts.config_schema.schema import AgentConfig
from backend.config_gate.errors import GateError
from backend.config_gate.service import AgentService


class AgentServiceConfigSource:
    """Adapts the studio `AgentService` to the orchestrator's `ConfigSource` seam."""

    def __init__(self, service: AgentService) -> None:
        self._service = service

    def get_config(self, agent_id: str, tenant_id: str) -> Optional[AgentConfig]:
        try:
            # AgentService scopes to the owner in code; user == tenant in dev.
            return self._service.get_agent(agent_id, tenant_id)
        except GateError:
            # NotFound (or any gate refusal) -> the orchestrator's "unknown agent" path,
            # which it turns into a clean 404. Never leak the reason across the seam.
            return None
