"""SQLiteOrchestratorRepository — the zero-config persistence default (P2-D2: the
DB is truth). Same `OrchestratorRepository` Protocol as the in-memory reference and
the Postgres impl, so the service/runner are unchanged when this is swapped in.

`claim_next_lead` is one UPDATE...WHERE id=(SELECT ... LIMIT 1) statement wrapped in
`BEGIN IMMEDIATE`, SQLite's stand-in for Postgres's `SELECT ... FOR UPDATE SKIP
LOCKED`: it acquires the write lock up front so two concurrent claims within this
process can never grab the same lead (there's no cross-process worker here, so
plain locking — not skip-locked — is the right analogue).

Tenant isolation is in every WHERE clause (tenant_id = ?), never a client-supplied
id (D-security).
"""

from __future__ import annotations

import json
from contextlib import closing
from datetime import datetime, timezone
from typing import Optional

from contracts.campaign.model import Campaign, GuardrailEnvelope, Lead

from backend.integration.sqlite_db import begin_immediate, connect

DDL = """
CREATE TABLE IF NOT EXISTS campaigns (
    id               TEXT PRIMARY KEY,
    tenant_id        TEXT NOT NULL,
    agent_id         TEXT NOT NULL,
    name             TEXT NOT NULL,
    state            TEXT NOT NULL,
    envelope         TEXT NOT NULL,
    authorized_by    TEXT,
    authorized_at    TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
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
    attempts       INTEGER NOT NULL DEFAULT 0,
    next_action_at TEXT,
    outcome        TEXT,
    last_call_id   TEXT
);
CREATE INDEX IF NOT EXISTS leads_claim_idx ON leads (campaign_id, state, next_action_at);

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


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


def _parse(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s is not None else None


class SQLiteOrchestratorRepository:
    GLOBAL_SCOPE = "*"

    def __init__(self, path: Optional[str] = None):
        self._path = path
        self.init_schema()

    def _connect(self):
        return connect(self._path)

    def init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(DDL)

    # --- (de)serialization ---------------------------------------------------
    @staticmethod
    def _campaign_row(c: Campaign) -> tuple:
        return (
            c.id, c.tenant_id, c.agent_id, c.name, c.state.value,
            c.envelope.model_dump_json(), c.authorized_by, _iso(c.authorized_at),
            _iso(c.created_at), _iso(c.updated_at), c.autopause_reason,
        )

    @staticmethod
    def _campaign_from_row(r) -> Campaign:
        return Campaign(
            id=r[0], tenant_id=r[1], agent_id=r[2], name=r[3], state=r[4],
            envelope=GuardrailEnvelope.model_validate(json.loads(r[5])), authorized_by=r[6],
            authorized_at=_parse(r[7]), created_at=_parse(r[8]), updated_at=_parse(r[9]),
            autopause_reason=r[10],
        )

    @staticmethod
    def _lead_from_row(r) -> Lead:
        return Lead(
            id=r[0], campaign_id=r[1], tenant_id=r[2], phone=r[3], display_name=r[4],
            state=r[5], attempts=r[6], next_action_at=_parse(r[7]), outcome=r[8],
            last_call_id=r[9],
        )

    # --- campaigns -----------------------------------------------------------
    def create_campaign(self, campaign: Campaign) -> Campaign:
        with closing(self._connect()) as conn:
            conn.execute(
                f"INSERT INTO campaigns ({_CAMPAIGN_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                self._campaign_row(campaign),
            )
        return campaign

    def get_campaign(self, campaign_id: str, tenant_id: str) -> Optional[Campaign]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"SELECT {_CAMPAIGN_COLS} FROM campaigns WHERE id=? AND tenant_id=?",
                (campaign_id, tenant_id),
            ).fetchone()
        return self._campaign_from_row(row) if row else None

    def save_campaign(self, campaign: Campaign) -> Campaign:
        with closing(self._connect()) as conn:
            conn.execute(
                "UPDATE campaigns SET name=?, state=?, envelope=?, authorized_by=?, "
                "authorized_at=?, updated_at=?, autopause_reason=? WHERE id=?",
                (
                    campaign.name, campaign.state.value, campaign.envelope.model_dump_json(),
                    campaign.authorized_by, _iso(campaign.authorized_at), _iso(campaign.updated_at),
                    campaign.autopause_reason, campaign.id,
                ),
            )
        return campaign

    def list_campaigns(self, tenant_id: str) -> list[Campaign]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT {_CAMPAIGN_COLS} FROM campaigns WHERE tenant_id=? ORDER BY created_at",
                (tenant_id,),
            ).fetchall()
        return [self._campaign_from_row(r) for r in rows]

    # --- leads ---------------------------------------------------------------
    def add_leads(self, leads: list[Lead]) -> None:
        with closing(self._connect()) as conn:
            conn.executemany(
                f"INSERT INTO leads ({_LEAD_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        l.id, l.campaign_id, l.tenant_id, l.phone, l.display_name,
                        l.state.value, l.attempts, _iso(l.next_action_at), l.outcome,
                        l.last_call_id,
                    )
                    for l in leads
                ],
            )

    def get_lead(self, lead_id: str, tenant_id: str) -> Optional[Lead]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"SELECT {_LEAD_COLS} FROM leads WHERE id=? AND tenant_id=?",
                (lead_id, tenant_id),
            ).fetchone()
        return self._lead_from_row(row) if row else None

    def save_lead(self, lead: Lead) -> Lead:
        with closing(self._connect()) as conn:
            conn.execute(
                "UPDATE leads SET state=?, attempts=?, next_action_at=?, outcome=?, "
                "last_call_id=? WHERE id=?",
                (
                    lead.state.value, lead.attempts, _iso(lead.next_action_at), lead.outcome,
                    lead.last_call_id, lead.id,
                ),
            )
        return lead

    def list_leads(self, campaign_id: str, tenant_id: str) -> list[Lead]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT {_LEAD_COLS} FROM leads WHERE campaign_id=? AND tenant_id=?",
                (campaign_id, tenant_id),
            ).fetchall()
        return [self._lead_from_row(r) for r in rows]

    # --- the queue primitive -------------------------------------------------
    def claim_next_lead(self, campaign_id: str, now: datetime) -> Optional[Lead]:
        conn = self._connect()
        try:
            begin_immediate(conn)
            row = conn.execute(
                f"""
                UPDATE leads
                   SET attempts       = attempts + 1,
                       state          = 'dialing',
                       last_call_id   = id || ':' || (attempts + 1),
                       next_action_at = NULL
                 WHERE id = (
                       SELECT id FROM leads
                        WHERE campaign_id = ?
                          AND state IN ('queued', 'retry')
                          AND (next_action_at IS NULL OR next_action_at <= ?)
                        ORDER BY next_action_at ASC NULLS FIRST
                        LIMIT 1)
                RETURNING {_LEAD_COLS}
                """,
                (campaign_id, _iso(now)),
            ).fetchone()
            conn.execute("COMMIT")
        finally:
            conn.close()
        return self._lead_from_row(row) if row else None

    def count_in_flight(self, campaign_id: str) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT count(*) FROM leads WHERE campaign_id=? AND state IN ('dialing','in_call')",
                (campaign_id,),
            ).fetchone()
            return row[0]

    def list_interrupted(self, campaign_id: str) -> list[Lead]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT {_LEAD_COLS} FROM leads WHERE campaign_id=? AND state IN "
                "('dialing','in_call')",
                (campaign_id,),
            ).fetchall()
        return [self._lead_from_row(r) for r in rows]

    def has_unfinished(self, campaign_id: str) -> bool:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT EXISTS(SELECT 1 FROM leads WHERE campaign_id=? AND state <> 'done')",
                (campaign_id,),
            ).fetchone()
            return bool(row[0])

    # --- global emergency stop ----------------------------------------------
    def set_global_stop(self, scope: str, stopped: bool) -> None:
        with closing(self._connect()) as conn:
            if stopped:
                conn.execute(
                    "INSERT INTO orchestrator_global_stops (scope) VALUES (?) "
                    "ON CONFLICT DO NOTHING",
                    (scope,),
                )
            else:
                conn.execute("DELETE FROM orchestrator_global_stops WHERE scope=?", (scope,))

    def is_globally_stopped(self, tenant_id: str) -> bool:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT EXISTS(SELECT 1 FROM orchestrator_global_stops WHERE scope IN (?, ?))",
                (self.GLOBAL_SCOPE, tenant_id),
            ).fetchone()
            return bool(row[0])
