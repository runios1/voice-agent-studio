"""AuthStore behavior — identical assertions run against both the in-memory
reference and the SQLite default (durability across a reopen is the point of the
whole feature, so that's asserted for SQLite specifically)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from backend.auth.store import InMemoryAuthStore
from backend.auth.sqlite_store import SQLiteAuthStore


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "sqlite":
        return SQLiteAuthStore(str(tmp_path / "auth.db"))
    return InMemoryAuthStore()


def test_get_or_create_user_is_idempotent(store):
    a = store.get_or_create_user("sub-1", "a@example.com", "Alice", None)
    b = store.get_or_create_user("sub-1", "a@example.com", "Alice", None)
    assert a.id == b.id


def test_get_or_create_user_refreshes_profile_fields(store):
    first = store.get_or_create_user("sub-1", "old@example.com", "Old Name", None)
    second = store.get_or_create_user("sub-1", "new@example.com", "New Name", "pic.png")
    assert second.id == first.id
    assert second.email == "new@example.com"
    assert second.name == "New Name"
    assert second.picture == "pic.png"
    assert store.get_user(first.id).email == "new@example.com"


def test_different_subs_are_different_users(store):
    a = store.get_or_create_user("sub-1", "a@example.com", "Alice", None)
    b = store.get_or_create_user("sub-2", "b@example.com", "Bob", None)
    assert a.id != b.id


def test_get_user_unknown_id_is_none(store):
    assert store.get_user("nope") is None


def test_session_round_trip(store):
    user = store.get_or_create_user("sub-1", "a@example.com", "Alice", None)
    token = store.create_session(user.id)
    assert store.get_session_user(token) == user.id


def test_expired_session_is_rejected(store):
    user = store.get_or_create_user("sub-1", "a@example.com", "Alice", None)
    token = store.create_session(user.id, ttl=timedelta(seconds=-1))
    assert store.get_session_user(token) is None


def test_unknown_session_token_is_none(store):
    assert store.get_session_user("not-a-real-token") is None


def test_delete_session_revokes_it(store):
    user = store.get_or_create_user("sub-1", "a@example.com", "Alice", None)
    token = store.create_session(user.id)
    store.delete_session(token)
    assert store.get_session_user(token) is None


def test_sqlite_persists_across_reopen(tmp_path):
    path = str(tmp_path / "auth.db")
    first = SQLiteAuthStore(path)
    user = first.get_or_create_user("sub-1", "a@example.com", "Alice", None)
    token = first.create_session(user.id)

    reopened = SQLiteAuthStore(path)
    assert reopened.get_user(user.id).email == "a@example.com"
    assert reopened.get_session_user(token) == user.id
