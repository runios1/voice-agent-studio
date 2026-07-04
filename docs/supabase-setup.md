# Free hosted Postgres with Supabase

The app is **durable by default** on local SQLite (`./.data/vas.db`), which needs
no setup. Point it at a free hosted Postgres when you want storage that lives
outside your machine — survives a redeploy, shared across processes, backed up.
Supabase's free tier is a good fit; any libpq-speaking Postgres works the same way.

Nothing in the code changes: `backend/integration/persistence.py` switches every
store (config, events, orchestrator, auth) to Postgres the moment `DATABASE_URL`
is set, and each store runs an idempotent `CREATE TABLE IF NOT EXISTS` at boot, so
an **empty** database bootstraps itself on first run — no migration step.

## 1. Create the project

1. Sign up at <https://supabase.com> (free, GitHub login works).
2. **New project** → name it, pick a region near you, set a **database password**
   (save it — it's in the connection string and shown only once).
3. Wait for provisioning (~1–2 min).

## 2. Get the connection string

Dashboard → **Connect** (top bar) → **Connection string** → **Session pooler**.

It looks like:

```
postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

Use the **Session pooler**, not the alternatives — this matters:

| Option | Port | IPv4 | LISTEN/NOTIFY | Use it? |
|---|---|---|---|---|
| **Session pooler** | 5432 | ✅ | ✅ | **Yes** |
| Transaction pooler | 6543 | ✅ | ❌ breaks | No |
| Direct connection | 5432 | ❌ IPv6-only¹ | ✅ | Only on IPv6 |

The events bus (`backend/events/postgres_store.py`) uses Postgres **LISTEN/NOTIFY**
for cross-process live fan-out. The transaction pooler (6543) multiplexes
connections per-statement and silently drops `LISTEN`, so the dashboard would go
quiet. The session pooler holds one connection per client and supports it.

¹ Supabase's direct host resolves to IPv6 only unless you buy the IPv4 add-on, so
the session pooler is the portable choice from most networks and cloud hosts.

## 3. Wire it up

Append `?sslmode=require` (Supabase requires TLS) and set the env var:

```bash
# in your .env  (see .env.example)
DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
```

Install the driver (already uncommented in `requirements.txt`):

```bash
pip install -r requirements.txt        # brings in psycopg[binary]
```

Boot the backend:

```bash
set -a && source .env && set +a
python -m backend.integrated_app
```

The logs should show `config: Postgres repository`, `events: Postgres store +
LISTEN/NOTIFY bus`, `orchestrator: Postgres repository`, `auth: Postgres store`.

## 4. Verify

Quick end-to-end check that the DSN connects and schema bootstraps:

```bash
python - <<'PY'
import os
from backend.integration.persistence import build_config_repository, using_postgres
assert using_postgres(), "DATABASE_URL not set"
build_config_repository()   # runs init_schema() against the real DB
print("OK: connected and schema bootstrapped")
PY
```

Then in the Supabase dashboard → **Table Editor** you should see the created
tables (`agents`, `agent_versions`, `events`, plus the orchestrator and auth
tables). Or **SQL Editor**:

```sql
select table_name from information_schema.tables where table_schema = 'public';
```

## Notes & limits

- **Free tier** pauses a project after ~1 week of inactivity (resumes on next
  connect) and caps storage at 500 MB — fine for development, not production load.
- **Secrets:** `DATABASE_URL` contains the DB password. Keep it in `.env`
  (gitignored) or your host's secret store — never commit it (repo convention §9).
- **Rotating the password:** Supabase → Settings → Database → reset; update
  `DATABASE_URL`. Data is unaffected.
- **Going back to SQLite:** unset `DATABASE_URL`. (Data does not migrate between
  the two — they're separate stores.)
- **Production:** the same `DATABASE_URL` seam points at any managed Postgres
  (Supabase paid, Neon, RDS, Cloud SQL). No code change.
