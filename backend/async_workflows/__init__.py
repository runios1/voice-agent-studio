"""P2-4 — Async workflows (post-call orchestration).

Consumes `contracts/tool_registry` and `contracts/events`. Reacts to `lead.outcome`
events by running platform-authored, idempotent post-call workflows (confirmation
email, CRM write, scheduled follow-up touches) against the tool registry, and emits
`tool.invoked` / `followup.scheduled` back to the event stream. See README.md.
"""
