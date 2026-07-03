"""Analytics aggregation — query-computed, no second store (grill decision).

The append-only log is the single source (P2-D5); analytics are derived from it on
demand, never a parallel copy that could drift from the audit record. These roll-ups
feed the dashboard tiles (P2-7): counts by type/severity, per-campaign outcome and
guardrail-trip tallies, and coarse time buckets for sparklines.

Everything here is tenant-scoped via the `EventQuery` it is handed — it cannot see
across tenants because the store never returns cross-tenant rows.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from contracts.events.schema import EventType
from backend.events.store import EventQuery, EventStore


@dataclass
class Aggregates:
    total: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    by_severity: dict[str, int] = field(default_factory=dict)
    by_campaign: dict[str, int] = field(default_factory=dict)
    lead_outcomes: dict[str, int] = field(default_factory=dict)
    guardrail_trips: dict[str, int] = field(default_factory=dict)  # guardrail name -> count

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "by_type": self.by_type,
            "by_severity": self.by_severity,
            "by_campaign": self.by_campaign,
            "lead_outcomes": self.lead_outcomes,
            "guardrail_trips": self.guardrail_trips,
        }


def aggregate(store: EventStore, q: EventQuery) -> Aggregates:
    """Compute roll-ups over the tenant-scoped slice `q` selects."""
    events = store.query(q)
    agg = Aggregates(total=len(events))
    types: Counter = Counter()
    sev: Counter = Counter()
    camp: Counter = Counter()
    outcomes: Counter = Counter()
    trips: Counter = Counter()

    for s in events:
        e = s.event
        types[e.type.value] += 1
        sev[e.severity.value] += 1
        if e.campaign_id:
            camp[e.campaign_id] += 1
        if e.type is EventType.LEAD_OUTCOME:
            outcome = e.payload.get("outcome")
            if outcome is not None:
                outcomes[str(outcome)] += 1
        if e.type is EventType.GUARDRAIL_TRIPPED:
            trips[str(e.payload.get("guardrail", "unknown"))] += 1

    agg.by_type = dict(types)
    agg.by_severity = dict(sev)
    agg.by_campaign = dict(camp)
    agg.lead_outcomes = dict(outcomes)
    agg.guardrail_trips = dict(trips)
    return agg


@dataclass
class TimeBucket:
    start: datetime
    count: int
    by_severity: dict[str, int]

    def to_dict(self) -> dict:
        return {
            "start": self.start.isoformat(),
            "count": self.count,
            "by_severity": self.by_severity,
        }


def time_series(
    store: EventStore, q: EventQuery, *, bucket_seconds: int = 3600
) -> list[TimeBucket]:
    """Coarse time-bucketed counts for sparklines. Buckets are aligned to the epoch
    so independent queries line up. Empty buckets are omitted (the dashboard fills
    gaps); ordering is chronological."""
    if bucket_seconds <= 0:
        raise ValueError("bucket_seconds must be positive")
    events = store.query(q)
    buckets: dict[int, TimeBucket] = {}
    for s in events:
        occurred = s.event.occurred_at
        epoch = int(occurred.replace(tzinfo=occurred.tzinfo or timezone.utc).timestamp())
        key = epoch - (epoch % bucket_seconds)
        b = buckets.get(key)
        if b is None:
            b = TimeBucket(
                start=datetime.fromtimestamp(key, tz=timezone.utc),
                count=0,
                by_severity={},
            )
            buckets[key] = b
        b.count += 1
        sv = s.event.severity.value
        b.by_severity[sv] = b.by_severity.get(sv, 0) + 1
    return [buckets[k] for k in sorted(buckets)]
