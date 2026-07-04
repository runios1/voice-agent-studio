"""User + session storage — the identity backing `current_user` across the whole
app. Same Protocol + InMemory/SQLite/Postgres split as config_gate/orchestrator/
events (D9 swap posture): sessions are server-side, opaque, revocable tokens — the
cookie carries only a random lookup key, never a signed claim, so logout/expiry is
a DB delete, not a client-side trust decision.

Identity comes ONLY from Google (google_sub is the durable key); email/name/picture
are refreshed from the provider on every login in case they changed.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Protocol

DEFAULT_SESSION_TTL = timedelta(days=30)


@dataclass(frozen=True)
class User:
    id: str
    google_sub: str
    email: str
    name: str
    picture: Optional[str]
    created_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AuthStore(Protocol):
    def get_or_create_user(
        self, google_sub: str, email: str, name: str, picture: Optional[str]
    ) -> User: ...

    def get_user(self, user_id: str) -> Optional[User]: ...

    def create_session(self, user_id: str, ttl: timedelta = DEFAULT_SESSION_TTL) -> str: ...

    def get_session_user(self, token: str) -> Optional[str]: ...

    def delete_session(self, token: str) -> None: ...


class InMemoryAuthStore:
    """Reference AuthStore. Backs tests; not durable (matches the other in-memory refs)."""

    def __init__(self) -> None:
        self._users: dict[str, User] = {}
        self._by_sub: dict[str, str] = {}  # google_sub -> user_id
        self._sessions: dict[str, tuple[str, datetime]] = {}  # token -> (user_id, expires_at)
        self._lock = threading.Lock()

    def get_or_create_user(
        self, google_sub: str, email: str, name: str, picture: Optional[str]
    ) -> User:
        with self._lock:
            user_id = self._by_sub.get(google_sub)
            if user_id is not None:
                existing = self._users[user_id]
                refreshed = User(
                    id=existing.id, google_sub=google_sub, email=email, name=name,
                    picture=picture, created_at=existing.created_at,
                )
                self._users[user_id] = refreshed
                return refreshed
            user_id = secrets.token_hex(16)
            user = User(
                id=user_id, google_sub=google_sub, email=email, name=name,
                picture=picture, created_at=_now(),
            )
            self._users[user_id] = user
            self._by_sub[google_sub] = user_id
            return user

    def get_user(self, user_id: str) -> Optional[User]:
        with self._lock:
            return self._users.get(user_id)

    def create_session(self, user_id: str, ttl: timedelta = DEFAULT_SESSION_TTL) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[token] = (user_id, _now() + ttl)
        return token

    def get_session_user(self, token: str) -> Optional[str]:
        with self._lock:
            entry = self._sessions.get(token)
            if entry is None:
                return None
            user_id, expires_at = entry
            if expires_at < _now():
                del self._sessions[token]
                return None
            return user_id

    def delete_session(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)
