"""Workstream P2-5 — Event stream + observability backbone (foundational).

The single append-only stream every Phase-2 component emits to (P2-D5). Four
consumers bind to the frozen `contracts/events` schema through this package:
dashboard (P2-7), auto-pause (P2-6), the compliance audit log, and analytics.

Public surface:
  * `EventService`     — the one emit/query/subscribe door (validate -> persist -> publish).
  * `EventStore`, `InMemoryEventStore`, `PostgresEventStore` — durable append-only log.
  * `EventBus`, `InMemoryEventBus`, `PostgresListenBus`     — live fan-out.
  * `EventQuery`, `StoredEvent`, `matches`                  — tenant-scoped read model.
  * `aggregate`, `time_series`                              — query-computed analytics.
  * `validate_payload`, `PAYLOAD_MODELS`                    — per-type payload schemas.
  * `EventError`, `EventValidationError`                    — typed errors (no stack traces).
  * `create_router`, `create_app`, `install_error_handler` — the FastAPI surface P2-7 mounts.
"""

from __future__ import annotations

from backend.events.analytics import Aggregates, TimeBucket, aggregate, time_series
from backend.events.bus import EventBus, InMemoryEventBus, Subscription
from backend.events.errors import EventError, EventValidationError
from backend.events.payloads import PAYLOAD_MODELS, LeadOutcome, validate_payload
from backend.events.postgres_store import PostgresEventStore, PostgresListenBus
from backend.events.router import create_app, create_router, install_error_handler
from backend.events.service import EventService
from backend.events.store import (
    EventQuery,
    EventStore,
    InMemoryEventStore,
    StoredEvent,
    matches,
)

__all__ = [
    "EventService",
    "EventStore",
    "InMemoryEventStore",
    "PostgresEventStore",
    "PostgresListenBus",
    "EventBus",
    "InMemoryEventBus",
    "Subscription",
    "EventQuery",
    "StoredEvent",
    "matches",
    "aggregate",
    "time_series",
    "Aggregates",
    "TimeBucket",
    "validate_payload",
    "PAYLOAD_MODELS",
    "LeadOutcome",
    "EventError",
    "EventValidationError",
    "create_router",
    "create_app",
    "install_error_handler",
]
