"""PostgresEventStore + PostgresListenBus — the production impls (D10: Postgres).

Same `EventStore` / `EventBus` seams as the in-memory reference, so `EventService`,
`analytics`, and the router are unchanged when these are swapped in. NOT exercised in
CI (no database in the fan-out env) — written to the frozen contract and live-tested
at integration. `psycopg` (v3) is imported LAZILY so the rest of `backend.events`
imports cleanly without the driver present (same pattern as config_gate).

APPEND-ONLY IS ENFORCED IN THE DATABASE, not just the API:
  * `seq BIGSERIAL` gives the monotonic total order the app relies on.
  * `payload JSONB` (schema evolves fast, D10).
  * A `BEFORE UPDATE OR DELETE` trigger RAISES — so even a direct SQL client cannot
    mutate or remove a stored event. The immutable log is the compliance proof
    (P2-D5); this is the structural backstop behind the no-mutation Protocol.
  * No index-free full scans on the hot path: indexes on (tenant_id, seq) and the
    correlation ids used by audit filters.

LIVE FAN-OUT via LISTEN/NOTIFY (grill decision): append `NOTIFY`s a per-tenant
channel with the new seq; `PostgresListenBus` LISTENs and, on wake, the subscriber
pulls the new rows from the store by seq. NOTIFY payloads are size-limited, so we
send only the seq and read the row back — the DB stays the single source.
"""

from __future__ import annotations

from typing import AsyncIterator, Optional

from contracts.events.schema import Event
from backend.events.store import EventQuery, StoredEvent, matches

DDL = """
CREATE TABLE IF NOT EXISTS events (
    seq          BIGSERIAL PRIMARY KEY,
    event_id     TEXT NOT NULL UNIQUE,
    type         TEXT NOT NULL,
    occurred_at  TIMESTAMPTZ NOT NULL,
    severity     TEXT NOT NULL,
    tenant_id    TEXT NOT NULL,
    campaign_id  TEXT,
    lead_id      TEXT,
    call_id      TEXT,
    agent_id     TEXT,
    payload      JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS events_tenant_seq_idx  ON events (tenant_id, seq);
CREATE INDEX IF NOT EXISTS events_tenant_type_idx ON events (tenant_id, type);
CREATE INDEX IF NOT EXISTS events_campaign_idx    ON events (tenant_id, campaign_id);
CREATE INDEX IF NOT EXISTS events_call_idx        ON events (tenant_id, call_id);
CREATE INDEX IF NOT EXISTS events_occurred_idx    ON events (tenant_id, occurred_at);

-- Append-only backstop: block UPDATE/DELETE at the database, not just the API.
CREATE OR REPLACE FUNCTION events_block_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'events is append-only (compliance audit log); % rejected', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS events_no_mutation ON events;
CREATE TRIGGER events_no_mutation
    BEFORE UPDATE OR DELETE ON events
    FOR EACH ROW EXECUTE FUNCTION events_block_mutation();

-- Live fan-out: announce each append on a per-tenant channel with the new seq.
CREATE OR REPLACE FUNCTION events_notify() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('events_' || NEW.tenant_id, NEW.seq::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS events_notify_trg ON events;
CREATE TRIGGER events_notify_trg
    AFTER INSERT ON events
    FOR EACH ROW EXECUTE FUNCTION events_notify();
"""

_COLS = "seq, event_id, type, occurred_at, severity, tenant_id, campaign_id, lead_id, call_id, agent_id, payload"


class PostgresEventStore:
    """Postgres-backed append-only `EventStore`. `dsn` is a libpq connection string."""

    def __init__(self, dsn: str):
        try:
            import psycopg  # lazy: keep the driver optional for CI/import
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise RuntimeError(
                "PostgresEventStore requires psycopg (v3): pip install 'psycopg[binary]'"
            ) from exc
        self._psycopg = psycopg
        self._dsn = dsn

    def _connect(self):
        return self._psycopg.connect(self._dsn)

    def init_schema(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(DDL)
            conn.commit()

    # --- row <-> StoredEvent -------------------------------------------------
    @staticmethod
    def _to_stored(row) -> StoredEvent:
        (seq, event_id, type_, occurred_at, severity, tenant_id, campaign_id,
         lead_id, call_id, agent_id, payload) = row
        event = Event(
            event_id=event_id, type=type_, occurred_at=occurred_at, severity=severity,
            tenant_id=tenant_id, campaign_id=campaign_id, lead_id=lead_id,
            call_id=call_id, agent_id=agent_id, payload=payload,
        )
        return StoredEvent(seq=seq, event=event)

    def append(self, event: Event) -> StoredEvent:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO events
                    (event_id, type, occurred_at, severity, tenant_id,
                     campaign_id, lead_id, call_id, agent_id, payload)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING seq
                """,
                (
                    event.event_id, event.type.value, event.occurred_at,
                    event.severity.value, event.tenant_id, event.campaign_id,
                    event.lead_id, event.call_id, event.agent_id,
                    self._psycopg.types.json.Jsonb(event.payload),
                ),
            )
            seq = cur.fetchone()[0]
            conn.commit()
        return StoredEvent(seq=seq, event=event)

    def query(self, q: EventQuery) -> list[StoredEvent]:
        where = ["tenant_id = %s"]
        args: list = [q.tenant_id]
        if q.types:
            where.append("type = ANY(%s)")
            args.append([t.value for t in q.types])
        if q.severities:
            where.append("severity = ANY(%s)")
            args.append([s.value for s in q.severities])
        for col, val in (
            ("campaign_id", q.campaign_id), ("lead_id", q.lead_id),
            ("call_id", q.call_id), ("agent_id", q.agent_id),
        ):
            if val is not None:
                where.append(f"{col} = %s")
                args.append(val)
        if q.since is not None:
            where.append("occurred_at >= %s")
            args.append(q.since)
        if q.until is not None:
            where.append("occurred_at < %s")
            args.append(q.until)
        if q.after_seq is not None:
            where.append("seq > %s")
            args.append(q.after_seq)

        sql = f"SELECT {_COLS} FROM events WHERE {' AND '.join(where)} ORDER BY seq ASC"
        if q.limit is not None:
            # newest N in chronological order: subquery desc-limit then re-sort asc.
            sql = (
                f"SELECT {_COLS} FROM (SELECT {_COLS} FROM events "
                f"WHERE {' AND '.join(where)} ORDER BY seq DESC LIMIT %s) sub ORDER BY seq ASC"
            )
            args.append(q.limit)

        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, args)
            rows = cur.fetchall()
        return [self._to_stored(r) for r in rows]

    def get(self, tenant_id: str, event_id: str) -> Optional[StoredEvent]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM events WHERE tenant_id = %s AND event_id = %s",
                (tenant_id, event_id),
            )
            row = cur.fetchone()
        return self._to_stored(row) if row else None


class PostgresListenBus:
    """Cross-process live bus over LISTEN/NOTIFY. On a NOTIFY (carrying the new seq),
    each subscriber reads the fresh rows from the store by seq and yields the ones
    matching its query. The DB stays the single source; NOTIFY only wakes readers.

    Publish is a NO-OP here: the INSERT trigger already NOTIFYs, so `EventService`'s
    post-append publish call has nothing to do (the DB did it transactionally). Kept
    on the interface so the service code path is identical to the in-memory bus."""

    def __init__(self, store: PostgresEventStore):
        self._store = store

    async def publish(self, stored: StoredEvent) -> None:  # pragma: no cover - no-op
        return  # the INSERT trigger already emitted NOTIFY transactionally

    def subscribe(self, query: EventQuery) -> "PostgresSubscription":
        return PostgresSubscription(self._store, query)


class PostgresSubscription:  # pragma: no cover - requires a live DB
    def __init__(self, store: PostgresEventStore, query: EventQuery):
        self._store = store
        self._query = query
        self._last_seq = query.after_seq or 0

    async def __aiter__(self) -> AsyncIterator[StoredEvent]:
        import psycopg

        channel = f"events_{self._query.tenant_id}"
        aconn = await psycopg.AsyncConnection.connect(self._store._dsn, autocommit=True)
        try:
            await aconn.execute(f'LISTEN "{channel}"')
            async for _notify in aconn.notifies():
                # Pull everything new since our cursor; matches() re-applies the filter.
                q = EventQuery(
                    tenant_id=self._query.tenant_id,
                    types=self._query.types,
                    severities=self._query.severities,
                    campaign_id=self._query.campaign_id,
                    lead_id=self._query.lead_id,
                    call_id=self._query.call_id,
                    agent_id=self._query.agent_id,
                    after_seq=self._last_seq,
                )
                for stored in self._store.query(q):
                    self._last_seq = max(self._last_seq, stored.seq)
                    if matches(self._query, stored):
                        yield stored
        finally:
            await aconn.close()

    def close(self) -> None:
        pass  # the async generator's finally closes the connection
