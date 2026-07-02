# Workstream 2 — Config gate + persistence

**Stack:** FastAPI + Postgres (`jsonb` config column) (D10). **Depends only on:**
`contracts/config_schema`.

## Responsibility — THE source-agnostic enforcement boundary (D-security)
Every mutation — builder tool-call, manual `PATCH`, or a forged request — passes
through the SAME gate. The LLM's triage is UX; THIS is security. For each mutation:
1. **Schema/type validation** against `schema.py`.
2. **Locked-path rejection** using `FIELD_POLICY` (server-side, even if UI already
   shows read-only). Never trust the client.
3. **Free-text screening** on prose fields (delegated to `backend/security`):
   hard-block anything touching a locked-guardrail domain (disclosure/DNC/claims);
   accept-but-flag merely-odd content (D-security decision 2).
4. On accept: apply patch, bump `meta.version`, persist. On reject: typed error
   (never a stack trace, D-reliability).

Also owns: **versioning/undo**, **tenant isolation** (all queries scoped to the
authed user by code, never by prompt), completeness evaluation
(`required_for_ready` all satisfied → `status = READY`).

## Boundaries — do NOT
- Do not call models here (that's builder/runtime). The gate is model-agnostic.
- Do not put secrets/infra detail anywhere reachable by a model's context.
