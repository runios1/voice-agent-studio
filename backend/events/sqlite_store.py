"""SQLiteEventStore — the zero-config persistence default for the durable,
append-only event log. Same `EventStore` Protocol as the in-memory reference and
the Postgres impl, so `EventService`/the router are unchanged when this is swapped
in. `payload` is a TEXT column holding the JSON blob (SQLite has no native jsonb).

APPEND-ONLY is enforced with a trigger, same as the Postgres impl's backstop, so
even a direct SQL client cannot mutate or remove a stored event.

Live fan-out stays the in-process `InMemoryEventBus` (single-process local server;
no LISTEN/NOTIFY equivalent needed) — durability lives here, liveness lives there,
same split `EventService` already expects.
"""

from __future__ import annotations

import json
from contextlib import closing
from typing import Optional

from contracts.events.schema import Event
from backend.events.store import EventQuery, StoredEvent

from backend.integration.sqlite_db import connect

DDL = """
CREATE TABLE IF NOT EXISTS events (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT NOT NULL UNIQUE,
    type         TEXT NOT NULL,
    occurred_at  TEXT NOT NULL,
    severity     TEXT NOT NULL,
    tenant_id    TEXT NOT NULL,
    campaign_id  TEXT,
    lead_id      TEXT,
    call_id      TEXT,
    agent_id     TEXT,
    payload      TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS events_tenant_seq_idx  ON events (tenant_id, seq);
CREATE INDEX IF NOT EXISTS events_tenant_type_idx ON events (tenant_id, type);
CREATE INDEX IF NOT EXISTS events_campaign_idx    ON events (tenant_id, campaign_id);
CREATE INDEX IF NOT EXISTS events_call_idx        ON events (tenant_id, call_id);
CREATE INDEX IF NOT EXISTS events_occurred_idx    ON events (tenant_id, occurred_at);

CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'events is append-only (compliance audit log); UPDATE rejected');
END;

CREATE TRIGGER IF NOT EXISTS events_no_delete
BEFORE DELETE ON events
BEGIN
    SELECT RAISE(ABORT, 'events is append-only (compliance audit log); DELETE rejected');
END;
"""

_COLS = (
    "seq, event_id, type, occurred_at, severity, tenant_id, campaign_id, lead_id, "
    "call_id, agent_id, payload"
)


class SQLiteEventStore:
    """SQLite-backed append-only `EventStore`. `path` is a filesystem path."""

    def __init__(self, path: Optional[str] = None):
        self._path = path
        self.init_schema()

    def _connect(self):
        return connect(self._path)

    def init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(DDL)

    @staticmethod
    def _to_stored(row) -> StoredEvent:
        (seq, event_id, type_, occurred_at, severity, tenant_id, campaign_id,
         lead_id, call_id, agent_id, payload) = row
        event = Event(
            event_id=event_id, type=type_, occurred_at=occurred_at, severity=severity,
            tenant_id=tenant_id, campaign_id=campaign_id, lead_id=lead_id,
            call_id=call_id, agent_id=agent_id, payload=json.loads(payload),
        )
        return StoredEvent(seq=seq, event=event)

    def append(self, event: Event) -> StoredEvent:
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                INSERT INTO events
                    (event_id, type, occurred_at, severity, tenant_id,
                     campaign_id, lead_id, call_id, agent_id, payload)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                RETURNING seq
                """,
                (
                    event.event_id, event.type.value, event.occurred_at.isoformat(),
                    event.severity.value, event.tenant_id, event.campaign_id,
                    event.lead_id, event.call_id, event.agent_id,
                    json.dumps(event.payload),
                ),
            ).fetchone()
        return StoredEvent(seq=row[0], event=event)

    def query(self, q: EventQuery) -> list[StoredEvent]:
        where = ["tenant_id = ?"]
        args: list = [q.tenant_id]
        if q.types:
            placeholders = ",".join("?" for _ in q.types)
            where.append(f"type IN ({placeholders})")
            args.extend(t.value for t in q.types)
        if q.severities:
            placeholders = ",".join("?" for _ in q.severities)
            where.append(f"severity IN ({placeholders})")
            args.extend(s.value for s in q.severities)
        for col, val in (
            ("campaign_id", q.campaign_id), ("lead_id", q.lead_id),
            ("call_id", q.call_id), ("agent_id", q.agent_id),
        ):
            if val is not None:
                where.append(f"{col} = ?")
                args.append(val)
        if q.since is not None:
            where.append("occurred_at >= ?")
            args.append(q.since.isoformat())
        if q.until is not None:
            where.append("occurred_at < ?")
            args.append(q.until.isoformat())
        if q.after_seq is not None:
            where.append("seq > ?")
            args.append(q.after_seq)

        sql = f"SELECT {_COLS} FROM events WHERE {' AND '.join(where)} ORDER BY seq ASC"
        if q.limit is not None:
            sql = (
                f"SELECT {_COLS} FROM (SELECT {_COLS} FROM events "
                f"WHERE {' AND '.join(where)} ORDER BY seq DESC LIMIT ?) sub ORDER BY seq ASC"
            )
            args.append(q.limit)

        with closing(self._connect()) as conn:
            rows = conn.execute(sql, args).fetchall()
        return [self._to_stored(r) for r in rows]

    def get(self, tenant_id: str, event_id: str) -> Optional[StoredEvent]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"SELECT {_COLS} FROM events WHERE tenant_id = ? AND event_id = ?",
                (tenant_id, event_id),
            ).fetchone()
        return self._to_stored(row) if row else None
