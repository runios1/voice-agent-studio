"""The durable, append-only event log — the compliance audit record (P2-D5).

Mirrors the config_gate split: a `EventStore` Protocol with an `InMemoryEventStore`
(backs CI + tests) and a `PostgresEventStore` (written to the frozen contract,
live-tested at integration, not run in CI — no DB in the fan-out env).

APPEND-ONLY IS STRUCTURAL, not a convention:
  * The Protocol exposes `append`, `query`, `get` — and deliberately NO update or
    delete. There is no code path to mutate a stored event (P2-5 boundary).
  * Total order is a monotonic `seq` assigned BY THE STORE at append time.
    `occurred_at` is emitter-supplied and can tie or skew; `seq` is the authority
    for ordering, cursoring (`after_seq`), and "what happened before what".
  * The Postgres impl additionally installs a trigger that raises on UPDATE/DELETE,
    so append-only holds even against a direct SQL client (defense in depth).

TENANT ISOLATION (D-security): `tenant_id` is required on every event and every
query is scoped by it in code. A subscriber/reader can never see another tenant's
stream — there is no unscoped read.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional, Protocol

from contracts.events.schema import Event, EventType, Severity


@dataclass(frozen=True)
class StoredEvent:
    """An `Event` plus the store-assigned monotonic sequence number.

    `seq` is global-monotonic across all tenants (a single append-only log); ordering
    *within a tenant* is still total because seq is strictly increasing. Frozen so a
    reader who holds one can't mutate the log by reference."""

    seq: int
    event: Event


@dataclass(frozen=True)
class EventQuery:
    """Tenant-scoped audit/query filter. `tenant_id` is mandatory and is applied in
    code — never overridable by a client-supplied field."""

    tenant_id: str
    types: Optional[frozenset[EventType]] = None
    severities: Optional[frozenset[Severity]] = None
    campaign_id: Optional[str] = None
    lead_id: Optional[str] = None
    call_id: Optional[str] = None
    agent_id: Optional[str] = None
    since: Optional[datetime] = None       # inclusive, on occurred_at
    until: Optional[datetime] = None       # exclusive, on occurred_at
    after_seq: Optional[int] = None        # exclusive cursor for pagination / catch-up
    limit: Optional[int] = None            # cap rows (newest-relative when combined w/ order)


def matches(query: EventQuery, stored: StoredEvent) -> bool:
    """Pure predicate: does this stored event satisfy the query? Shared by the
    in-memory store AND the live bus (so a subscriber's filter and an audit query
    mean exactly the same thing)."""
    e = stored.event
    if e.tenant_id != query.tenant_id:
        return False
    if query.types is not None and e.type not in query.types:
        return False
    if query.severities is not None and e.severity not in query.severities:
        return False
    if query.campaign_id is not None and e.campaign_id != query.campaign_id:
        return False
    if query.lead_id is not None and e.lead_id != query.lead_id:
        return False
    if query.call_id is not None and e.call_id != query.call_id:
        return False
    if query.agent_id is not None and e.agent_id != query.agent_id:
        return False
    if query.since is not None and e.occurred_at < query.since:
        return False
    if query.until is not None and e.occurred_at >= query.until:
        return False
    if query.after_seq is not None and stored.seq <= query.after_seq:
        return False
    return True


class EventStore(Protocol):
    """Append-only, tenant-scoped storage seam. No mutation methods exist by design."""

    def append(self, event: Event) -> StoredEvent: ...

    def query(self, q: EventQuery) -> list[StoredEvent]: ...

    def get(self, tenant_id: str, event_id: str) -> Optional[StoredEvent]: ...


class InMemoryEventStore:
    """Reference `EventStore`. Thread-safe append (workers emit concurrently), deep-copies
    on the way out so a reader cannot mutate the persisted log by holding a reference —
    the same immutability a real append-only table gives for free."""

    def __init__(self) -> None:
        self._events: list[StoredEvent] = []
        self._by_id: dict[str, StoredEvent] = {}
        self._lock = threading.Lock()
        self._next_seq = 1

    def append(self, event: Event) -> StoredEvent:
        with self._lock:
            stored = StoredEvent(seq=self._next_seq, event=event.model_copy(deep=True))
            self._next_seq += 1
            self._events.append(stored)
            # event_id is expected unique; last-writer indexing is fine (ids are uuids).
            self._by_id[event.event_id] = stored
            return stored

    def query(self, q: EventQuery) -> list[StoredEvent]:
        with self._lock:
            snapshot = list(self._events)
        out = [s for s in snapshot if matches(q, s)]
        out.sort(key=lambda s: s.seq)  # total order by seq, ascending
        if q.limit is not None:
            # newest N, but still returned in chronological (seq-ascending) order
            out = out[-q.limit :]
        return [self._deepcopy(s) for s in out]

    def get(self, tenant_id: str, event_id: str) -> Optional[StoredEvent]:
        with self._lock:
            stored = self._by_id.get(event_id)
        if stored is None or stored.event.tenant_id != tenant_id:
            return None  # missing OR not-yours — indistinguishable (isolation)
        return self._deepcopy(stored)

    def all_for_tenant(self, tenant_id: str) -> Iterable[StoredEvent]:
        """Convenience for aggregation — a tenant-scoped full scan, chronological."""
        return self.query(EventQuery(tenant_id=tenant_id))

    @staticmethod
    def _deepcopy(s: StoredEvent) -> StoredEvent:
        return StoredEvent(seq=s.seq, event=s.event.model_copy(deep=True))
