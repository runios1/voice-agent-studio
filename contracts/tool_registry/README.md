# tool_registry/ — capability registry (Phase 2, FROZEN)

Generalizes `backend/runtime_loop/tools.build_tools()` into a curated catalog
(P2-D4). Capability == an exposed function, nothing more; params are least-privilege;
every tool runs against a per-tenant `Connection` (encrypted, tenant-scoped). Tools
are keyed by automation-block name, so **no config-schema change is required**.
Handlers/impl live in P2-3.
