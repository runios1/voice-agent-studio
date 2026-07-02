"""Persistence — tenant-scoped storage with full-snapshot versioning (D10, D-defaults).

Two responsibilities live here, deliberately behind one interface so the gate and
service stay storage-agnostic:

  * TENANT ISOLATION — every method takes `owner_user_id` and filters by it *in
    code*. There is no way to read or write another tenant's agent: a mismatched
    owner reads as "not found" (existence is not leaked). We NEVER trust a
    client-supplied owner id (D-security, conventions).

  * VERSIONING — full config snapshots, one per accepted mutation. Revert is
    therefore O(1) and dead-simple (append a copy of an old snapshot as a new
    version); ideal for a jsonb column. `meta.version` is the latest version
    number. Optimistic concurrency: `save(expected_version=N)` refuses if the
    stored latest has moved on (a concurrent edit won).

`ConfigRepository` is the Protocol the service depends on. `InMemoryConfigRepository`
backs tests and CI. `PostgresConfigRepository` (postgres_repository.py) implements
the same Protocol against Postgres jsonb for production — swappable, no gate change.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Protocol

from contracts.config_schema.schema import AgentConfig, AgentMeta
from backend.config_gate.errors import ErrorKind, GateError


@dataclass
class StoredVersion:
    version: int
    config: AgentConfig
    created_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ConflictError(GateError):
    def __init__(self, path: Optional[str] = None):
        super().__init__(
            ErrorKind.CONFLICT,
            "This agent changed since you loaded it — reload and try again.",
            path,
        )


class NotFoundError(GateError):
    def __init__(self, agent_id: str):
        super().__init__(ErrorKind.NOT_FOUND, "No such agent.", agent_id)


class ConfigRepository(Protocol):
    """Storage seam. All reads/writes are scoped to `owner_user_id` in code."""

    def create(self, config: AgentConfig) -> AgentConfig: ...

    def get(self, agent_id: str, owner_user_id: str) -> Optional[AgentConfig]: ...

    def save(
        self, config: AgentConfig, owner_user_id: str, expected_version: Optional[int] = None
    ) -> AgentConfig: ...

    def list_meta(self, owner_user_id: str) -> list[AgentMeta]: ...

    def list_versions(self, agent_id: str, owner_user_id: str) -> list[StoredVersion]: ...

    def get_version(
        self, agent_id: str, owner_user_id: str, version: int
    ) -> Optional[AgentConfig]: ...


class InMemoryConfigRepository:
    """Reference implementation of ConfigRepository. Tenant-scoped, versioned.

    Stores deep copies on the way in and out so callers can't mutate persisted
    state by holding a reference (the same isolation a real DB gives for free).
    """

    def __init__(self) -> None:
        # agent_id -> ordered list of StoredVersion (index 0 == version 1)
        self._versions: dict[str, list[StoredVersion]] = {}
        # agent_id -> owner, for O(1) tenant checks without deserializing
        self._owner: dict[str, str] = {}

    # --- helpers -------------------------------------------------------------
    def _owned(self, agent_id: str, owner_user_id: str) -> bool:
        return self._owner.get(agent_id) == owner_user_id

    def _latest(self, agent_id: str) -> Optional[StoredVersion]:
        chain = self._versions.get(agent_id)
        return chain[-1] if chain else None

    # --- interface -----------------------------------------------------------
    def create(self, config: AgentConfig) -> AgentConfig:
        agent_id = config.meta.id
        if agent_id in self._versions:
            raise GateError(ErrorKind.CONFLICT, "Agent already exists.", agent_id)
        stored = copy.deepcopy(config)
        stored.meta.version = 1
        self._versions[agent_id] = [StoredVersion(1, stored, _now())]
        self._owner[agent_id] = config.meta.owner_user_id
        return copy.deepcopy(stored)

    def get(self, agent_id: str, owner_user_id: str) -> Optional[AgentConfig]:
        if not self._owned(agent_id, owner_user_id):
            return None  # missing OR not yours — indistinguishable on purpose
        latest = self._latest(agent_id)
        return copy.deepcopy(latest.config) if latest else None

    def save(
        self, config: AgentConfig, owner_user_id: str, expected_version: Optional[int] = None
    ) -> AgentConfig:
        agent_id = config.meta.id
        if not self._owned(agent_id, owner_user_id):
            raise NotFoundError(agent_id)
        latest = self._latest(agent_id)
        assert latest is not None  # owned => at least one version exists
        if expected_version is not None and expected_version != latest.version:
            raise ConflictError(agent_id)
        new_version = latest.version + 1
        stored = copy.deepcopy(config)
        stored.meta.version = new_version
        stored.meta.updated_at = _now()
        self._versions[agent_id].append(StoredVersion(new_version, stored, _now()))
        return copy.deepcopy(stored)

    def list_meta(self, owner_user_id: str) -> list[AgentMeta]:
        out: list[AgentMeta] = []
        for agent_id, owner in self._owner.items():
            if owner != owner_user_id:
                continue
            latest = self._latest(agent_id)
            if latest:
                out.append(copy.deepcopy(latest.config.meta))
        return out

    def list_versions(self, agent_id: str, owner_user_id: str) -> list[StoredVersion]:
        if not self._owned(agent_id, owner_user_id):
            return []
        return [copy.deepcopy(v) for v in self._versions.get(agent_id, [])]

    def get_version(
        self, agent_id: str, owner_user_id: str, version: int
    ) -> Optional[AgentConfig]:
        if not self._owned(agent_id, owner_user_id):
            return None
        for v in self._versions.get(agent_id, []):
            if v.version == version:
                return copy.deepcopy(v.config)
        return None
