# P2-3 — Tool registry + integrations

**Consumes:** `contracts/tool_registry`. **Depended on by:** P2-1, P2-4.

## Responsibility
- The curated tool **catalog** (≥ calendar + email v1): each a `RegistryTool` with a
  least-privilege param schema, timing (in-call/post-call), provider + scopes.
- **Per-tenant OAuth connections**: connect flow, **encrypted, tenant-scoped** token
  storage behind `CredentialStore`; execution always runs against the tenant's own
  connection.
- `ToolHandler`s that enforce guardrails **in code** (business hours, allowlisted
  link domains, scope limits) — the enforcement point (D6/D-security).
- Wishlist→registry graduation is just adding a catalog entry (P2-D4).

## Boundaries — do NOT
- Do not expose a capability without a least-privilege param schema (no free-composed
  URLs/bodies, no `offer_discount`).
- Do not let a tenant reach another tenant's connection — deny by code, not prompt.
- Curated, not self-serve: users connect accounts, they don't invent tools.
