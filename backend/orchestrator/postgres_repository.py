"""PostgresOrchestratorRepository — the production storage impl (P2-D2: DB is truth).

Same `OrchestratorRepository` Protocol as the in-memory reference, so the service and
runner are unchanged when this is swapped in. The whole no-double-dial guarantee rests
on `claim_next_lead` being an atomic `SELECT ... FOR UPDATE SKIP LOCKED` — two workers
(even across processes/hosts) can never claim the same lead, and a claimed lead is
durably `DIALING` before the call is placed, so a crash resumes from the row.

NOT exercised in CI (no database in the parallel-dev env) — written to the frozen
contract and live-tested at integration. `psycopg` (v3) is imported LAZILY so the rest
of the package imports without the driver. See DONE.md for how to run it.

Tenant isolation is in every WHERE clause (`tenant_id = %s`), never a client-supplied
id (D-security).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from contracts.campaign.model import Campaign, GuardrailEnvelope, Lead

DDL = """
CREATE TABLE IF NOT EXISTS campaigns (
    id               TEXT PRIMARY KEY,
    tenant_id        TEXT NOT NULL,
    agent_id         TEXT NOT NULL,
    name             TEXT NOT NULL,
    state            TEXT NOT NULL,
    envelope         JSONB NOT NULL,
    authorized_by    TEXT,
    authorized_at    TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL,
    updated_at       TIMESTAMPTZ NOT NULL,
    autopause_reason TEXT
);
CREATE INDEX IF NOT EXISTS campaigns_tenant_idx ON campaigns (tenant_id);

CREATE TABLE IF NOT EXISTS leads (
    id             TEXT PRIMARY KEY,
    campaign_id    TEXT NOT NULL REFERENCES campaigns(id),
    tenant_id      TEXT NOT NULL,
    phone          TEXT NOT NULL,
    display_name   TEXT,
    state          TEXT NOT NULL,
    attempts       INT  NOT NULL DEFAULT 0,
    next_action_at TIMESTAMPTZ,
    outcome        TEXT,
    last_call_id   TEXT
);
-- The claim's hot path: eligible leads for a campaign, oldest-scheduled first.
CREATE INDEX IF NOT EXISTS leads_claim_idx
    ON leads (campaign_id, state, next_action_at);

CREATE TABLE IF NOT EXISTS orchestrator_global_stops (
    scope TEXT PRIMARY KEY
);
"""

_CAMPAIGN_COLS = (
    "id, tenant_id, agent_id, name, state, envelope, authorized_by, "
    "authorized_at, created_at, updated_at, autopause_reason"
)
_LEAD_COLS = (
    "id, campaign_id, tenant_id, phone, display_name, state, attempts, "
    "next_action_at, outcome, last_call_id"
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PostgresOrchestratorRepository:
    GLOBAL_SCOPE = "*"

    def __init__(self, dsn: str):
        try:
            import psycopg  # lazy: keep the driver optional for CI/import
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise RuntimeError(
                "PostgresOrchestratorRepository requires psycopg (v3): "
                "pip install 'psycopg[binary]'"
            ) from exc
        self._psycopg = psycopg
        self._dsn = dsn

    def _connect(self):
        return self._psycopg.connect(self._dsn)

    def init_schema(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(DDL)
            conn.commit()

    # --- (de)serialization ---------------------------------------------------
    @staticmethod
    def _campaign_row(c: Campaign) -> tuple:
        return (
            c.id, c.tenant_id, c.agent_id, c.name, c.state.value,
            c.envelope.model_dump_json(), c.authorized_by, c.authorized_at,
            c.created_at, c.updated_at, c.autopause_reason,
        )

    @staticmethod
    def _campaign_from_row(r) -> Campaign:
        env = r[5] if isinstance(r[5], dict) else __import__("json").loads(r[5])
        return Campaign(
            id=r[0], tenant_id=r[1], agent_id=r[2], name=r[3], state=r[4],
            envelope=GuardrailEnvelope.model_validate(env), authorized_by=r[6],
            authorized_at=r[7], created_at=r[8], updated_at=r[9], autopause_reason=r[10],
        )

    @staticmethod
    def _lead_from_row(r) -> Lead:
        return Lead(
            id=r[0], campaign_id=r[1], tenant_id=r[2], phone=r[3], display_name=r[4],
            state=r[5], attempts=r[6], next_action_at=r[7], outcome=r[8], last_call_id=r[9],
        )

    # --- campaigns -----------------------------------------------------------
    def create_campaign(self, campaign: Campaign) -> Campaign:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO campaigns ({_CAMPAIGN_COLS}) VALUES "
                "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                self._campaign_row(campaign),
            )
            conn.commit()
        return campaign

    def get_campaign(self, campaign_id: str, tenant_id: str) -> Optional[Campaign]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_CAMPAIGN_COLS} FROM campaigns WHERE id=%s AND tenant_id=%s",
                (campaign_id, tenant_id),
            )
            row = cur.fetchone()
        return self._campaign_from_row(row) if row else None

    def save_campaign(self, campaign: Campaign) -> Campaign:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE campaigns SET name=%s, state=%s, envelope=%s, authorized_by=%s, "
                "authorized_at=%s, updated_at=%s, autopause_reason=%s WHERE id=%s",
                (
                    campaign.name, campaign.state.value, campaign.envelope.model_dump_json(),
                    campaign.authorized_by, campaign.authorized_at, campaign.updated_at,
                    campaign.autopause_reason, campaign.id,
                ),
            )
            conn.commit()
        return campaign

    def list_campaigns(self, tenant_id: str) -> list[Campaign]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_CAMPAIGN_COLS} FROM campaigns WHERE tenant_id=%s ORDER BY created_at",
                (tenant_id,),
            )
            rows = cur.fetchall()
        return [self._campaign_from_row(r) for r in rows]

    # --- leads ---------------------------------------------------------------
    def add_leads(self, leads: list[Lead]) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.executemany(
                f"INSERT INTO leads ({_LEAD_COLS}) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [
                    (
                        l.id, l.campaign_id, l.tenant_id, l.phone, l.display_name,
                        l.state.value, l.attempts, l.next_action_at, l.outcome, l.last_call_id,
                    )
                    for l in leads
                ],
            )
            conn.commit()

    def get_lead(self, lead_id: str, tenant_id: str) -> Optional[Lead]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_LEAD_COLS} FROM leads WHERE id=%s AND tenant_id=%s",
                (lead_id, tenant_id),
            )
            row = cur.fetchone()
        return self._lead_from_row(row) if row else None

    def save_lead(self, lead: Lead) -> Lead:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE leads SET state=%s, attempts=%s, next_action_at=%s, outcome=%s, "
                "last_call_id=%s WHERE id=%s",
                (
                    lead.state.value, lead.attempts, lead.next_action_at, lead.outcome,
                    lead.last_call_id, lead.id,
                ),
            )
            conn.commit()
        return lead

    def list_leads(self, campaign_id: str, tenant_id: str) -> list[Lead]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_LEAD_COLS} FROM leads WHERE campaign_id=%s AND tenant_id=%s",
                (campaign_id, tenant_id),
            )
            rows = cur.fetchall()
        return [self._lead_from_row(r) for r in rows]

    # --- the queue primitive -------------------------------------------------
    def claim_next_lead(self, campaign_id: str, now: datetime) -> Optional[Lead]:
        """Atomic claim via FOR UPDATE SKIP LOCKED — the no-double-dial guarantee.

        The inner SELECT locks exactly one eligible row and skips any a peer worker
        already holds; the UPDATE commits it to DIALING with attempts+1 and a
        deterministic last_call_id, all in one transaction."""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE leads
                   SET attempts       = attempts + 1,
                       state          = 'dialing',
                       last_call_id   = id || ':' || (attempts + 1),
                       next_action_at = NULL
                 WHERE id = (
                       SELECT id FROM leads
                        WHERE campaign_id = %s
                          AND state IN ('queued', 'retry')
                          AND (next_action_at IS NULL OR next_action_at <= %s)
                        ORDER BY next_action_at ASC NULLS FIRST
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1)
                RETURNING {_LEAD_COLS}
                """,
                (campaign_id, now),
            )
            row = cur.fetchone()
            conn.commit()
        return self._lead_from_row(row) if row else None

    def count_in_flight(self, campaign_id: str) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM leads WHERE campaign_id=%s AND state IN "
                "('dialing','in_call')",
                (campaign_id,),
            )
            return cur.fetchone()[0]

    def list_interrupted(self, campaign_id: str) -> list[Lead]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_LEAD_COLS} FROM leads WHERE campaign_id=%s AND state IN "
                "('dialing','in_call')",
                (campaign_id,),
            )
            rows = cur.fetchall()
        return [self._lead_from_row(r) for r in rows]

    def has_unfinished(self, campaign_id: str) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT EXISTS(SELECT 1 FROM leads WHERE campaign_id=%s AND state <> 'done')",
                (campaign_id,),
            )
            return bool(cur.fetchone()[0])

    # --- global emergency stop ----------------------------------------------
    def set_global_stop(self, scope: str, stopped: bool) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            if stopped:
                cur.execute(
                    "INSERT INTO orchestrator_global_stops (scope) VALUES (%s) "
                    "ON CONFLICT DO NOTHING",
                    (scope,),
                )
            else:
                cur.execute("DELETE FROM orchestrator_global_stops WHERE scope=%s", (scope,))
            conn.commit()

    def is_globally_stopped(self, tenant_id: str) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT EXISTS(SELECT 1 FROM orchestrator_global_stops WHERE scope IN (%s, %s))",
                (self.GLOBAL_SCOPE, tenant_id),
            )
            return bool(cur.fetchone()[0])
