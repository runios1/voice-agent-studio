"""SQLiteConfigRepository — the zero-config persistence default (no DATABASE_URL
needed). Same `ConfigRepository` Protocol as the in-memory reference and the
Postgres impl, so the gate/service are unchanged when this is swapped in. Config
lives in a TEXT column holding the JSON snapshot (SQLite has no native jsonb).

Tenant isolation is enforced in every WHERE clause (owner_user_id = ?), never by a
prompt or a client-supplied id (D-security). Optimistic concurrency is a
compare-and-append inside one `BEGIN IMMEDIATE` transaction (SQLite's stand-in for
Postgres's `SELECT ... FOR UPDATE`).
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from typing import Optional

from contracts.config_schema.schema import AgentConfig, AgentMeta
from backend.config_gate.repository import ConflictError, NotFoundError, StoredVersion
from backend.integration.sqlite_db import begin_immediate, connect

DDL = """
CREATE TABLE IF NOT EXISTS agents (
    id             TEXT PRIMARY KEY,
    owner_user_id  TEXT NOT NULL,
    latest_version INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS agents_owner_idx ON agents (owner_user_id);

CREATE TABLE IF NOT EXISTS agent_versions (
    agent_id   TEXT NOT NULL REFERENCES agents(id),
    version    INTEGER NOT NULL,
    config     TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (agent_id, version)
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SQLiteConfigRepository:
    """SQLite-backed ConfigRepository. `path` is a filesystem path (default under
    `./.data`); pass `:memory:` only for a throwaway single-connection test."""

    def __init__(self, path: Optional[str] = None):
        self._path = path
        self.init_schema()

    def _connect(self):
        return connect(self._path)

    def init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(DDL)

    @staticmethod
    def _dump(config: AgentConfig) -> str:
        return config.model_dump_json()

    @staticmethod
    def _load(raw: str) -> AgentConfig:
        return AgentConfig.model_validate_json(raw)

    def create(self, config: AgentConfig) -> AgentConfig:
        config.meta.version = 1
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO agents (id, owner_user_id, latest_version) VALUES (?, ?, 1)",
                (config.meta.id, config.meta.owner_user_id),
            )
            conn.execute(
                "INSERT INTO agent_versions (agent_id, version, config, created_at) "
                "VALUES (?, 1, ?, ?)",
                (config.meta.id, self._dump(config), _now().isoformat()),
            )
        return config

    def get(self, agent_id: str, owner_user_id: str) -> Optional[AgentConfig]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT v.config
                FROM agents a
                JOIN agent_versions v
                  ON v.agent_id = a.id AND v.version = a.latest_version
                WHERE a.id = ? AND a.owner_user_id = ?
                """,
                (agent_id, owner_user_id),
            ).fetchone()
        return self._load(row[0]) if row else None

    def save(
        self, config: AgentConfig, owner_user_id: str, expected_version: Optional[int] = None
    ) -> AgentConfig:
        agent_id = config.meta.id
        conn = self._connect()
        try:
            begin_immediate(conn)
            row = conn.execute(
                "SELECT latest_version FROM agents WHERE id = ? AND owner_user_id = ?",
                (agent_id, owner_user_id),
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                raise NotFoundError(agent_id)
            latest = row[0]
            if expected_version is not None and expected_version != latest:
                conn.execute("ROLLBACK")
                raise ConflictError(agent_id)
            new_version = latest + 1
            config.meta.version = new_version
            config.meta.updated_at = _now()
            conn.execute(
                "INSERT INTO agent_versions (agent_id, version, config, created_at) "
                "VALUES (?, ?, ?, ?)",
                (agent_id, new_version, self._dump(config), _now().isoformat()),
            )
            conn.execute(
                "UPDATE agents SET latest_version = ? WHERE id = ?", (new_version, agent_id)
            )
            conn.execute("COMMIT")
        finally:
            conn.close()
        return config

    def list_meta(self, owner_user_id: str) -> list[AgentMeta]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT v.config
                FROM agents a
                JOIN agent_versions v
                  ON v.agent_id = a.id AND v.version = a.latest_version
                WHERE a.owner_user_id = ?
                """,
                (owner_user_id,),
            ).fetchall()
        return [self._load(r[0]).meta for r in rows]

    def list_versions(self, agent_id: str, owner_user_id: str) -> list[StoredVersion]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT v.version, v.config, v.created_at
                FROM agent_versions v
                JOIN agents a ON a.id = v.agent_id
                WHERE v.agent_id = ? AND a.owner_user_id = ?
                ORDER BY v.version ASC
                """,
                (agent_id, owner_user_id),
            ).fetchall()
        return [
            StoredVersion(version=r[0], config=self._load(r[1]), created_at=datetime.fromisoformat(r[2]))
            for r in rows
        ]

    def get_version(
        self, agent_id: str, owner_user_id: str, version: int
    ) -> Optional[AgentConfig]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT v.config
                FROM agent_versions v
                JOIN agents a ON a.id = v.agent_id
                WHERE v.agent_id = ? AND a.owner_user_id = ? AND v.version = ?
                """,
                (agent_id, owner_user_id, version),
            ).fetchone()
        return self._load(row[0]) if row else None
