"""Integration layer — where the merged workstreams are wired into ONE real product.

Phase 2 shipped each workstream green against mocks; the `phase2_app` / `integrated_app`
composition roots wired them with STUB collaborators (a default ConfigSource, a scripted
dialer, no auto-run, in-memory only). This package holds the *real* wiring — the pieces
that turn "green in isolation" into "a campaign a user authorizes actually loads the agent
they built, dials real leads over a real transport, runs real tools, and persists".

Everything here is a thin adapter over a frozen seam — no new business logic. Each module
maps one stub to its real collaborator:

  * `config_source`  — orchestrator ConfigSource  -> the studio's AgentService (real agent)
  * `runtime`        — builds the real VoiceRuntime + per-agent ToolRegistry + shared stores
  * `dialer`         — orchestrator Dialer -> VoiceRuntime over a pluggable transport
  * `supervisor`     — auto-runs an authorized campaign's dispatch loop (bounded autonomy)
  * `persistence`    — DATABASE_URL-toggled Postgres vs. in-memory stores
"""
