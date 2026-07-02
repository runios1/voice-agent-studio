"""The due-time scheduler for deferred follow-up touches.

A SCHEDULE step doesn't run its follow-up now — it parks a `ScheduledAction` with a
`run_at`. `tick(engine)` fires everything now due through the engine. Time is read
through the injected `Clock`, so tests advance a `ManualClock` to make a 24h delay
due instantly (no real sleep).

Enqueue is idempotent on `ScheduledAction.id` (which is deterministic, derived from
the originating run): replaying the same outcome re-enqueues the same id and the
store dedupes it, so a lead never accrues two identical timers. In-memory store;
the interface is the seam for a durable `run_at`-indexed table + poller later.
"""

from __future__ import annotations

from typing import Protocol

from .clock import Clock
from .models import ScheduledAction


class ScheduleStore(Protocol):
    async def add(self, action: ScheduledAction) -> bool: ...   # False if id already present
    async def pop_due(self, now) -> list[ScheduledAction]: ...


class InMemoryScheduleStore:
    def __init__(self) -> None:
        self._actions: dict[str, ScheduledAction] = {}

    async def add(self, action: ScheduledAction) -> bool:
        if action.id in self._actions:
            return False
        self._actions[action.id] = action
        return True

    async def pop_due(self, now) -> list[ScheduledAction]:
        due = [a for a in self._actions.values() if a.run_at <= now]
        for a in due:
            del self._actions[a.id]
        return sorted(due, key=lambda a: a.run_at)


class FollowupScheduler:
    def __init__(self, clock: Clock, store: ScheduleStore | None = None) -> None:
        self._clock = clock
        self._store = store or InMemoryScheduleStore()

    async def schedule(self, action: ScheduledAction) -> bool:
        """Park a follow-up. Returns False if this exact action was already scheduled
        (idempotent replay)."""
        return await self._store.add(action)

    async def tick(self, engine) -> list:
        """Run every action now due. Each fires as a fresh run whose idempotency root
        is the action id, so the deferred touch actually executes (it isn't fenced by
        the original outcome's keys) while still being replay-safe on its own id."""
        now = self._clock.now()
        due = await self._store.pop_due(now)
        runs = []
        for action in due:
            runs.append(await engine.run(action.workflow, action.trigger))
        return runs
