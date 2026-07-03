"""Storage selection — Postgres when `DATABASE_URL` is set, in-memory otherwise, in ONE
place. Each Postgres class already implements the SAME Protocol as its in-memory
reference and lazily imports psycopg, so selection is a pure factory choice with no code
path change downstream (the whole point of the frozen repository seams).

Set `DATABASE_URL` to a libpq connection string to persist config, events, and campaign
state across restarts; leave it unset for a zero-dependency dev/CI boot.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

log = logging.getLogger("voice_agent_studio.persistence")


def database_url() -> Optional[str]:
    return os.getenv("DATABASE_URL") or None


def using_postgres() -> bool:
    return database_url() is not None


def build_config_repository():
    """The config repository the studio + orchestrator read the built agent from."""
    dsn = database_url()
    if dsn:
        from backend.config_gate.postgres_repository import PostgresConfigRepository

        log.info("config: Postgres repository")
        return PostgresConfigRepository(dsn)
    from backend.config_gate.repository import InMemoryConfigRepository

    return InMemoryConfigRepository()


def build_event_service():
    """The one event log threaded everywhere as the orchestrator's sink (contract §4)."""
    from backend.events.service import EventService

    dsn = database_url()
    if dsn:
        from backend.events.postgres_store import PostgresEventStore, PostgresListenBus

        store = PostgresEventStore(dsn)
        log.info("events: Postgres store + LISTEN/NOTIFY bus")
        return EventService(store=store, bus=PostgresListenBus(store))
    return EventService()


def build_orchestrator_repository():
    """Per-lead campaign state — the DB is the source of truth for resume-after-crash."""
    dsn = database_url()
    if dsn:
        from backend.orchestrator.postgres_repository import PostgresOrchestratorRepository

        log.info("orchestrator: Postgres repository")
        return PostgresOrchestratorRepository(dsn)
    from backend.orchestrator.repository import InMemoryOrchestratorRepository

    return InMemoryOrchestratorRepository()
