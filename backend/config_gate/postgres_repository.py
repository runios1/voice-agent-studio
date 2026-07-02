"""PostgresConfigRepository — the production storage impl (D10: Postgres + jsonb).

Same `ConfigRepository` Protocol as the in-memory reference, so the gate/service
are unchanged when this is swapped in. Config lives in a `jsonb` column because
the schema evolves fast (D10) and we store full snapshots per version.

NOT exercised in CI (no database in the parallel-dev env) — it is written to the
frozen contract and live-tested at integration time. It uses psycopg (v3), which
is imported LAZILY so the rest of config_gate imports cleanly without the driver
present. See DONE.md for the DDL and how to run it against a real Postgres.

Tenant isolation is enforced in every WHERE clause (owner_user_id = %s), never by
a prompt or a client-supplied id (D-security). Optimistic concurrency is a
compare-and-append inside one transaction.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from contracts.config_schema.schema import AgentConfig, AgentMeta
from backend.config_gate.repository import (
    ConflictError,
    NotFoundError,
    StoredVersion,
)

DDL = """
CREATE TABLE IF NOT EXISTS agents (
    id             TEXT PRIMARY KEY,
    owner_user_id  TEXT NOT NULL,
    latest_version INT  NOT NULL
);
CREATE INDEX IF NOT EXISTS agents_owner_idx ON agents (owner_user_id);

CREATE TABLE IF NOT EXISTS agent_versions (
    agent_id   TEXT NOT NULL REFERENCES agents(id),
    version    INT  NOT NULL,
    config     JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, version)
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PostgresConfigRepository:
    """Postgres-backed ConfigRepository. `dsn` is a standard libpq connection string."""

    def __init__(self, dsn: str):
        try:
            import psycopg  # lazy: keep the driver optional for CI/import
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise RuntimeError(
                "PostgresConfigRepository requires psycopg (v3): pip install 'psycopg[binary]'"
            ) from exc
        self._psycopg = psycopg
        self._dsn = dsn

    def _connect(self):
        return self._psycopg.connect(self._dsn)

    def init_schema(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(DDL)
            conn.commit()

    # --- serialization helpers ----------------------------------------------
    @staticmethod
    def _dump(config: AgentConfig) -> str:
        # mode="json" => datetimes become ISO strings, safe for jsonb.
        return config.model_dump_json()

    @staticmethod
    def _load(raw) -> AgentConfig:
        # psycopg returns jsonb as a Python dict already.
        return AgentConfig.model_validate(raw)

    # --- interface -----------------------------------------------------------
    def create(self, config: AgentConfig) -> AgentConfig:
        config.meta.version = 1
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO agents (id, owner_user_id, latest_version) VALUES (%s, %s, 1)",
                (config.meta.id, config.meta.owner_user_id),
            )
            cur.execute(
                "INSERT INTO agent_versions (agent_id, version, config) VALUES (%s, 1, %s)",
                (config.meta.id, self._dump(config)),
            )
            conn.commit()
        return config

    def get(self, agent_id: str, owner_user_id: str) -> Optional[AgentConfig]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT v.config
                FROM agents a
                JOIN agent_versions v
                  ON v.agent_id = a.id AND v.version = a.latest_version
                WHERE a.id = %s AND a.owner_user_id = %s
                """,
                (agent_id, owner_user_id),
            )
            row = cur.fetchone()
        return self._load(row[0]) if row else None

    def save(
        self, config: AgentConfig, owner_user_id: str, expected_version: Optional[int] = None
    ) -> AgentConfig:
        agent_id = config.meta.id
        with self._connect() as conn, conn.cursor() as cur:
            # Lock the agent row so the compare-and-append is atomic.
            cur.execute(
                "SELECT latest_version FROM agents WHERE id = %s AND owner_user_id = %s FOR UPDATE",
                (agent_id, owner_user_id),
            )
            row = cur.fetchone()
            if row is None:
                raise NotFoundError(agent_id)
            latest = row[0]
            if expected_version is not None and expected_version != latest:
                raise ConflictError(agent_id)
            new_version = latest + 1
            config.meta.version = new_version
            config.meta.updated_at = _now()
            cur.execute(
                "INSERT INTO agent_versions (agent_id, version, config) VALUES (%s, %s, %s)",
                (agent_id, new_version, self._dump(config)),
            )
            cur.execute(
                "UPDATE agents SET latest_version = %s WHERE id = %s",
                (new_version, agent_id),
            )
            conn.commit()
        return config

    def list_meta(self, owner_user_id: str) -> list[AgentMeta]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT v.config
                FROM agents a
                JOIN agent_versions v
                  ON v.agent_id = a.id AND v.version = a.latest_version
                WHERE a.owner_user_id = %s
                """,
                (owner_user_id,),
            )
            rows = cur.fetchall()
        return [self._load(r[0]).meta for r in rows]

    def list_versions(self, agent_id: str, owner_user_id: str) -> list[StoredVersion]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT v.version, v.config, v.created_at
                FROM agent_versions v
                JOIN agents a ON a.id = v.agent_id
                WHERE v.agent_id = %s AND a.owner_user_id = %s
                ORDER BY v.version ASC
                """,
                (agent_id, owner_user_id),
            )
            rows = cur.fetchall()
        return [StoredVersion(version=r[0], config=self._load(r[1]), created_at=r[2]) for r in rows]

    def get_version(
        self, agent_id: str, owner_user_id: str, version: int
    ) -> Optional[AgentConfig]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT v.config
                FROM agent_versions v
                JOIN agents a ON a.id = v.agent_id
                WHERE v.agent_id = %s AND a.owner_user_id = %s AND v.version = %s
                """,
                (agent_id, owner_user_id, version),
            )
            row = cur.fetchone()
        return self._load(row[0]) if row else None
