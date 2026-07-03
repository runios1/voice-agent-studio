"""EventService — the one door every emitter and consumer uses.

Composes the durable `EventStore` with the live `EventBus`. It is the emit boundary
where the D-reliability chain closes for events: **constrain -> validate -> persist
-> publish**.

  emit(...):
    1. fill envelope defaults (event_id uuid4, occurred_at server-side if absent),
    2. VALIDATE the payload against its per-type model (reject before persisting),
    3. build the frozen `contracts/events` `Event`,
    4. APPEND to the durable store (assigns the monotonic seq),
    5. PUBLISH to the live bus (best-effort fan-out).

Durability-before-liveness: the store write happens before the bus publish, so a
crash can never lose an event a subscriber saw but the log missed.

TENANT ISOLATION (D-security): `tenant_id` is a required arg on emit and on every
read; there is no unscoped query or subscribe. A consumer sees exactly one tenant.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import ValidationError

from contracts.events.schema import Event, EventType, Severity
from backend.events.bus import EventBus, InMemoryEventBus, Subscription
from backend.events.errors import EventValidationError
from backend.events.payloads import validate_payload
from backend.events.store import EventQuery, EventStore, InMemoryEventStore, StoredEvent


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EventService:
    def __init__(self, store: Optional[EventStore] = None, bus: Optional[EventBus] = None):
        self._store: EventStore = store or InMemoryEventStore()
        self._bus: EventBus = bus or InMemoryEventBus()

    # --- emit ---------------------------------------------------------------
    async def emit(
        self,
        type: EventType,
        *,
        tenant_id: str,
        payload: Optional[dict[str, Any]] = None,
        severity: Severity = Severity.INFO,
        campaign_id: Optional[str] = None,
        lead_id: Optional[str] = None,
        call_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        occurred_at: Optional[datetime] = None,
        event_id: Optional[str] = None,
    ) -> StoredEvent:
        """Validate + persist + publish one event. Returns the StoredEvent (with seq).

        `tenant_id` is mandatory (isolation). Missing `event_id`/`occurred_at` are
        filled server-side so all six emitting streams stay consistent without
        boilerplate."""
        if not tenant_id:
            raise EventValidationError("tenant_id is required on every event.")

        try:
            normalized = validate_payload(type, payload or {})
        except ValidationError as exc:
            # Never leak a stack trace; report which fields failed.
            raise EventValidationError(
                f"Invalid payload for {type.value}.",
                detail="; ".join(
                    f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
                ),
            ) from exc

        event = Event(
            event_id=event_id or str(uuid.uuid4()),
            type=type,
            occurred_at=occurred_at or _now(),
            severity=severity,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            lead_id=lead_id,
            call_id=call_id,
            agent_id=agent_id,
            payload=normalized,
        )
        stored = self._store.append(event)  # durable first
        await self._bus.publish(stored)     # then live fan-out
        return stored

    def emit_sync(self, type: EventType, **kwargs: Any) -> StoredEvent:
        """Synchronous emit for non-async emitters (e.g. a sync worker). Validates +
        persists; live publish is skipped (subscribers still get it on `after_seq`
        catch-up from the durable store). Use `emit` from async code."""
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.emit(type, **kwargs))
        raise RuntimeError("emit_sync called from an async context — use `await emit(...)`.")

    # --- audit query / export ----------------------------------------------
    def query(self, q: EventQuery) -> list[StoredEvent]:
        """Tenant-scoped audit query. `q.tenant_id` is enforced in the store."""
        return self._store.query(q)

    def get(self, tenant_id: str, event_id: str) -> Optional[StoredEvent]:
        return self._store.get(tenant_id, event_id)

    def export_ndjson(self, q: EventQuery) -> str:
        """Export the audit slice as newline-delimited JSON (one frozen-contract
        Event per line, chronological). Streamable and diff-friendly for compliance
        hand-off. seq travels in an envelope key so ordering survives re-import."""
        lines = []
        for s in self._store.query(q):
            lines.append(
                '{"seq": %d, "event": %s}' % (s.seq, s.event.model_dump_json())
            )
        return "\n".join(lines)

    # --- live subscribe -----------------------------------------------------
    def subscribe(self, q: EventQuery) -> Subscription:
        """Live tenant-scoped subscription. Pair with a `query(after_seq=...)` replay
        to guarantee no gap between backfill and live tail (see router)."""
        return self._bus.subscribe(q)
