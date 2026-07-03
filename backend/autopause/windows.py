"""Event-time sliding-window counters, keyed for tenant isolation.

Why event-time (`Event.occurred_at`) and not wall-clock: it makes detection
deterministic and replay-safe. A synthetic sequence of events with fixed
timestamps trips (or doesn't) the same way every run, and re-reading the durable
log reproduces exactly what happened live — the audit story P2-D5 depends on.

Keys are `(tenant_id, campaign_id)` tuples so one tenant's traffic can never bleed
into another's counter (D-security: tenant isolation, always in code)."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Hashable


class SlidingWindow:
    """Counts occurrences per key within `window_seconds` of the latest event.

    `add(key, at)` records an occurrence and returns the number of occurrences for
    that key still inside the window (inclusive of the one just added). Timestamps
    older than `at - window` are evicted lazily on each add."""

    def __init__(self, window_seconds: float) -> None:
        self._window = timedelta(seconds=window_seconds)
        self._events: dict[Hashable, deque[datetime]] = defaultdict(deque)

    def add(self, key: Hashable, at: datetime) -> int:
        dq = self._events[key]
        dq.append(at)
        cutoff = at - self._window
        # Evict anything strictly older than the window relative to this event.
        while dq and dq[0] < cutoff:
            dq.popleft()
        return len(dq)

    def count(self, key: Hashable) -> int:
        return len(self._events.get(key, ()))

    def reset(self, key: Hashable) -> None:
        self._events.pop(key, None)
