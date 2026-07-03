"""Shared fixtures for the event-backbone tests."""

from __future__ import annotations

import pytest

from backend.events.service import EventService
from backend.events.store import InMemoryEventStore
from backend.events.bus import InMemoryEventBus

TENANT = "tenant-acme"
OTHER = "tenant-globex"


@pytest.fixture
def store() -> InMemoryEventStore:
    return InMemoryEventStore()


@pytest.fixture
def bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture
def service(store: InMemoryEventStore, bus: InMemoryEventBus) -> EventService:
    return EventService(store=store, bus=bus)
