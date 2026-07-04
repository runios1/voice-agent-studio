"""Storage selection, in ONE place: Postgres when `DATABASE_URL` is set, else SQLite
(a file under `SQLITE_DB_PATH`, default `./.data/vas.db`) — a real, durable default
with zero external services to stand up. Every store implements the SAME Protocol
as its in-memory reference and lazily imports its driver, so selection is a pure
factory choice with no code path change downstream (the whole point of the frozen
repository seams).

Set `DATABASE_URL` to a libpq connection string to persist to Postgres instead
(e.g. a free Supabase project — see `docs/supabase-setup.md`); each factory runs
its store's idempotent `init_schema()` (CREATE TABLE IF NOT EXISTS) at boot, so
pointing at an empty database just works — no manual migration step. Set
`VAS_IN_MEMORY=true` for a zero-dependency ephemeral boot (tests/CI only —
nothing survives a restart).
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


def _in_memory_only() -> bool:
    return os.getenv("VAS_IN_MEMORY", "false").lower() == "true"


def using_durable_storage() -> bool:
    """True when agents/campaigns/events/accounts actually survive a restart
    (Postgres or SQLite) — False only for the explicit ephemeral test/CI mode."""
    return not _in_memory_only()


def build_config_repository():
    """The config repository the studio + orchestrator read the built agent from."""
    if _in_memory_only():
        from backend.config_gate.repository import InMemoryConfigRepository

        return InMemoryConfigRepository()
    dsn = database_url()
    if dsn:
        from backend.config_gate.postgres_repository import PostgresConfigRepository

        repo = PostgresConfigRepository(dsn)
        repo.init_schema()  # idempotent CREATE TABLE IF NOT EXISTS — bootstraps a fresh DB
        log.info("config: Postgres repository")
        return repo
    from backend.config_gate.sqlite_repository import SQLiteConfigRepository

    log.info("config: SQLite repository")
    return SQLiteConfigRepository()


def build_event_service():
    """The one event log threaded everywhere as the orchestrator's sink (contract §4)."""
    from backend.events.service import EventService

    if _in_memory_only():
        return EventService()
    dsn = database_url()
    if dsn:
        from backend.events.postgres_store import PostgresEventStore, PostgresListenBus

        store = PostgresEventStore(dsn)
        store.init_schema()  # idempotent — creates events table + NOTIFY trigger on a fresh DB
        log.info("events: Postgres store + LISTEN/NOTIFY bus")
        return EventService(store=store, bus=PostgresListenBus(store))
    from backend.events.sqlite_store import SQLiteEventStore

    log.info("events: SQLite store + in-process bus")
    return EventService(store=SQLiteEventStore())


def build_orchestrator_repository():
    """Per-lead campaign state — the DB is the source of truth for resume-after-crash."""
    if _in_memory_only():
        from backend.orchestrator.repository import InMemoryOrchestratorRepository

        return InMemoryOrchestratorRepository()
    dsn = database_url()
    if dsn:
        from backend.orchestrator.postgres_repository import PostgresOrchestratorRepository

        repo = PostgresOrchestratorRepository(dsn)
        repo.init_schema()  # idempotent — bootstraps per-lead campaign-state tables
        log.info("orchestrator: Postgres repository")
        return repo
    from backend.orchestrator.sqlite_repository import SQLiteOrchestratorRepository

    log.info("orchestrator: SQLite repository")
    return SQLiteOrchestratorRepository()


def build_auth_store():
    """User accounts + sessions — durable by default (same posture as the rest)."""
    if _in_memory_only():
        from backend.auth.store import InMemoryAuthStore

        return InMemoryAuthStore()
    dsn = database_url()
    if dsn:
        from backend.auth.postgres_store import PostgresAuthStore

        store = PostgresAuthStore(dsn)
        store.init_schema()  # idempotent — bootstraps users + sessions tables
        log.info("auth: Postgres store")
        return store
    from backend.auth.sqlite_store import SQLiteAuthStore

    log.info("auth: SQLite store")
    return SQLiteAuthStore()
