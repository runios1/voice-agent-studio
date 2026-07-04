"""SQLiteAuthStore — the zero-config persistence default for user accounts +
sessions (no DATABASE_URL needed). Same `AuthStore` Protocol as `InMemoryAuthStore`.
"""

from __future__ import annotations

import secrets
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.auth.store import DEFAULT_SESSION_TTL, User
from backend.integration.sqlite_db import connect

DDL = """
CREATE TABLE IF NOT EXISTS users (
    id         TEXT PRIMARY KEY,
    google_sub TEXT NOT NULL UNIQUE,
    email      TEXT NOT NULL,
    name       TEXT NOT NULL,
    picture    TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id),
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SQLiteAuthStore:
    def __init__(self, path: Optional[str] = None):
        self._path = path
        self.init_schema()

    def _connect(self):
        return connect(self._path)

    def init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(DDL)

    @staticmethod
    def _user_from_row(r) -> User:
        return User(
            id=r[0], google_sub=r[1], email=r[2], name=r[3], picture=r[4],
            created_at=datetime.fromisoformat(r[5]),
        )

    def get_or_create_user(
        self, google_sub: str, email: str, name: str, picture: Optional[str]
    ) -> User:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT id, created_at FROM users WHERE google_sub=?", (google_sub,)
            ).fetchone()
            if row is not None:
                conn.execute(
                    "UPDATE users SET email=?, name=?, picture=? WHERE google_sub=?",
                    (email, name, picture, google_sub),
                )
                return User(
                    id=row[0], google_sub=google_sub, email=email, name=name,
                    picture=picture, created_at=datetime.fromisoformat(row[1]),
                )
            user_id = secrets.token_hex(16)
            now = _now()
            conn.execute(
                "INSERT INTO users (id, google_sub, email, name, picture, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (user_id, google_sub, email, name, picture, now.isoformat()),
            )
            return User(
                id=user_id, google_sub=google_sub, email=email, name=name,
                picture=picture, created_at=now,
            )

    def get_user(self, user_id: str) -> Optional[User]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT id, google_sub, email, name, picture, created_at FROM users WHERE id=?",
                (user_id,),
            ).fetchone()
        return self._user_from_row(row) if row else None

    def create_session(self, user_id: str, ttl: timedelta = DEFAULT_SESSION_TTL) -> str:
        token = secrets.token_urlsafe(32)
        expires_at = _now() + ttl
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO sessions (token, user_id, expires_at) VALUES (?,?,?)",
                (token, user_id, expires_at.isoformat()),
            )
        return token

    def get_session_user(self, token: str) -> Optional[str]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT user_id, expires_at FROM sessions WHERE token=?", (token,)
            ).fetchone()
            if row is None:
                return None
            user_id, expires_at = row
            if datetime.fromisoformat(expires_at) < _now():
                conn.execute("DELETE FROM sessions WHERE token=?", (token,))
                return None
            return user_id
        finally:
            conn.close()

    def delete_session(self, token: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM sessions WHERE token=?", (token,))
