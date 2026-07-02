# P2-5 — Event stream + observability backbone  *(foundational — merges first)*

**Consumes:** `contracts/events`. **Depended on by:** P2-6, P2-7, and every emitter.

## Responsibility
- The event **bus** (emit + live subscribe) and **durable, append-only persistence**
  — the immutable log IS the compliance audit record (P2-D5).
- **Per-type payload validation** (the contract keeps `payload` a generic dict on
  purpose; you own the per-`EventType` payload schemas).
- Query/filter/export for the audit log; aggregation for analytics.
- Live transport toward the dashboard (SSE/WS — your grill decision).

## Boundaries — do NOT
- Do not let events be mutated or deleted (append-only, always).
- Do not add domain logic (auto-pause is P2-6; that only *reads* your stream).
- Tenant is always present on an event; never leak cross-tenant on subscribe/query.
