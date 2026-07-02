# FROZEN CONTRACT — API contract (v1)

The seam between **frontend (workstream 1)** and **backend (workstreams 2–6)**.
Freeze this before fan-out. Transport: HTTP + **Server-Sent Events** for streaming
(D10). All endpoints are auth-scoped to the current user; the server NEVER trusts a
client-supplied `owner_user_id` (tenant isolation, D-security).

## Auth
- `POST /auth/login` — minimal single-provider OAuth (D-defaults). Returns session.

## Agents (a user may own many — D-defaults)
- `GET  /agents` — list the user's agents (meta only).
- `POST /agents` — create a new draft agent. Returns `AgentConfig` seeded with the
  platform layer already populated (locked guardrails + defaults).
- `GET  /agents/{id}` — full `AgentConfig`. Includes resolved `FIELD_POLICY` so the
  panel can render lock badges + editability without a second call.
- `GET  /agents/{id}/history` — version list; `POST /agents/{id}/revert/{version}` — undo.

## Builder loop (chat that EDITS the config — D5)
- `POST /agents/{id}/builder/messages` (SSE) — send a user turn.
  Server streams back two interleaved event kinds:
  - `token` — assistant reply text (materializes the conversational answer);
  - `patch` — an accepted config mutation `{path, value}` (materializes a panel field).
  Rejected mutations (locked path, failed validation, failed screening) are NOT
  emitted as patches; instead a `notice` event explains, conversationally.

## Config gate (manual edits — same gate as the builder, D-security)
- `PATCH /agents/{id}/fields` — body `{path, value}`. Applies the IDENTICAL
  server-side gate as builder patches: schema/type validation → locked-path
  rejection → free-text screening. Returns the accepted patch or a typed error.
  This endpoint is the manual-edit door; it is NOT a bypass.

## Runtime loop (chat that EXECUTES the config — preview, D12)
- `POST /agents/{id}/preview/messages` (SSE) — talk **to** the agent (not the
  builder). Streams the agent's response per its configured persona/goal/guardrails.
  Phase 1: text only, no tools, no voice. Phase 2: swap I/O for the voice Live API.

## Error shape (typed, so the UI degrades gracefully — never a stack trace, D-reliability)
```json
{ "error": { "kind": "locked_path|validation|screening_blocked|screening_flagged|rate_limited",
             "path": "conversation.disclosure.must_disclose_ai",
             "message": "human-friendly, conversational explanation" } }
```
