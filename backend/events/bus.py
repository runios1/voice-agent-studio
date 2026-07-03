"""The live fan-out half of the stream — pub/sub for subscribers (dashboard P2-7,
auto-pause P2-6).

The store is the *durable* half; the bus is the *live* half. `EventService` writes
to the store first (durability wins) then publishes to the bus, so a crash can never
lose an event that a live subscriber saw.

In-memory impl (CI/tests + single-process dev): each subscriber gets its own
`asyncio.Queue`; `publish` fans a stored event to every queue whose tenant-scoped
filter matches. Bounded queues + drop-oldest-on-overflow so one slow subscriber
(e.g. a stalled browser tab) can never block emit or leak memory — the durable log
is always the source of truth, and a lagging subscriber catches up via
`after_seq` replay from the store.

Production (documented, not run in CI): `PostgresListenBus` uses Postgres
LISTEN/NOTIFY so the same live fan-out works across processes without new infra —
the DB we already run is the bus. Grill decision: "Postgres LISTEN/NOTIFY (prod) +
in-memory async pub/sub (CI)."
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional, Protocol

from backend.events.store import EventQuery, StoredEvent, matches


class EventBus(Protocol):
    async def publish(self, stored: StoredEvent) -> None: ...

    def subscribe(self, query: EventQuery) -> "Subscription": ...


class Subscription:
    """One live subscriber. Async-iterates matching events as they are published.

    Backpressure policy: a bounded queue that DROPS THE OLDEST buffered event when
    full rather than blocking the publisher. Live transport is best-effort by design
    — the durable store (queried via `after_seq`) is the authority, so a UI that
    briefly falls behind reconciles against it instead of stalling the whole bus."""

    _CLOSED = object()

    def __init__(self, bus: "InMemoryEventBus", query: EventQuery, maxsize: int = 1000):
        self._bus = bus
        self._query = query
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._dropped = 0

    def _offer(self, stored: StoredEvent) -> None:
        if not matches(self._query, stored):
            return
        try:
            self._queue.put_nowait(stored)
        except asyncio.QueueFull:
            # drop the oldest, enqueue the newest — never block the publisher.
            try:
                self._queue.get_nowait()
                self._dropped += 1
            except asyncio.QueueEmpty:  # pragma: no cover - race, harmless
                pass
            self._queue.put_nowait(stored)

    async def __aiter__(self) -> AsyncIterator[StoredEvent]:
        try:
            while True:
                item = await self._queue.get()
                if item is self._CLOSED:
                    return
                yield item
        finally:
            self.close()

    async def get(self, timeout: Optional[float] = None) -> Optional[StoredEvent]:
        """Await the next event. Returns None if the subscription was closed, or
        raises `asyncio.TimeoutError` if `timeout` elapses first. Cancelling this
        coroutine only cancels a bare `Queue.get` — no generator state to corrupt —
        so the router can safely race it against a disconnect poll."""
        if timeout is None:
            item = await self._queue.get()
        else:
            item = await asyncio.wait_for(self._queue.get(), timeout=timeout)
        return None if item is self._CLOSED else item

    def close(self) -> None:
        self._bus._remove(self)
        # unblock a pending __anext__ so the generator can exit
        try:
            self._queue.put_nowait(self._CLOSED)
        except asyncio.QueueFull:  # pragma: no cover
            pass

    @property
    def dropped(self) -> int:
        return self._dropped


class InMemoryEventBus:
    """Single-process live bus. Subscribers register a tenant-scoped query; publish
    fans out to all matching subscriptions synchronously (put_nowait, non-blocking)."""

    def __init__(self) -> None:
        self._subs: set[Subscription] = set()

    def subscribe(self, query: EventQuery) -> Subscription:
        sub = Subscription(self, query)
        self._subs.add(sub)
        return sub

    def _remove(self, sub: Subscription) -> None:
        self._subs.discard(sub)

    async def publish(self, stored: StoredEvent) -> None:
        # snapshot avoids "set changed size during iteration" if a sub closes mid-fan-out
        for sub in list(self._subs):
            sub._offer(stored)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)
