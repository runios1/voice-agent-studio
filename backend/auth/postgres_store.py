"""PostgresAuthStore — the production storage impl, same `AuthStore` Protocol as
the SQLite/in-memory references (D9 swap posture). NOT exercised in CI/this sandbox
(no live Postgres available) — `psycopg` (v3) is imported LAZILY so the rest of
`backend.auth` imports cleanly without the driver present, same pattern as the
other three subsystems' Postgres impls.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.auth.store import DEFAULT_SESSION_TTL, User

DDL = """
CREATE TABLE IF NOT EXISTS users (
    id         TEXT PRIMARY KEY,
    google_sub TEXT NOT NULL UNIQUE,
    email      TEXT NOT NULL,
    name       TEXT NOT NULL,
    picture    TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PostgresAuthStore:
    def __init__(self, dsn: str):
        try:
            import psycopg  # lazy: keep the driver optional for CI/import
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise RuntimeError(
                "PostgresAuthStore requires psycopg (v3): pip install 'psycopg[binary]'"
            ) from exc
        self._psycopg = psycopg
        self._dsn = dsn

    def _connect(self):
        return self._psycopg.connect(self._dsn)

    def init_schema(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(DDL)
            conn.commit()

    @staticmethod
    def _user_from_row(r) -> User:
        return User(id=r[0], google_sub=r[1], email=r[2], name=r[3], picture=r[4], created_at=r[5])

    def get_or_create_user(
        self, google_sub: str, email: str, name: str, picture: Optional[str]
    ) -> User:
        import uuid

        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, created_at FROM users WHERE google_sub = %s", (google_sub,)
            )
            row = cur.fetchone()
            if row is not None:
                cur.execute(
                    "UPDATE users SET email = %s, name = %s, picture = %s WHERE google_sub = %s",
                    (email, name, picture, google_sub),
                )
                conn.commit()
                return User(
                    id=row[0], google_sub=google_sub, email=email, name=name,
                    picture=picture, created_at=row[1],
                )
            user_id = uuid.uuid4().hex
            now = _now()
            cur.execute(
                "INSERT INTO users (id, google_sub, email, name, picture, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (user_id, google_sub, email, name, picture, now),
            )
            conn.commit()
            return User(
                id=user_id, google_sub=google_sub, email=email, name=name,
                picture=picture, created_at=now,
            )

    def get_user(self, user_id: str) -> Optional[User]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, google_sub, email, name, picture, created_at FROM users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()
        return self._user_from_row(row) if row else None

    def create_session(self, user_id: str, ttl: timedelta = DEFAULT_SESSION_TTL) -> str:
        import secrets

        token = secrets.token_urlsafe(32)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sessions (token, user_id, expires_at) VALUES (%s,%s,%s)",
                (token, user_id, _now() + ttl),
            )
            conn.commit()
        return token

    def get_session_user(self, token: str) -> Optional[str]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, expires_at FROM sessions WHERE token = %s", (token,)
            )
            row = cur.fetchone()
            if row is None:
                return None
            user_id, expires_at = row
            if expires_at < _now():
                cur.execute("DELETE FROM sessions WHERE token = %s", (token,))
                conn.commit()
                return None
            return user_id

    def delete_session(self, token: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE token = %s", (token,))
            conn.commit()
