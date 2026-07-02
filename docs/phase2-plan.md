# Phase 2 plan — tooling, autonomy, dashboard

Phase 1 built the skeleton: chat → config → text preview, all guardrailed. Phase 2
makes agents **act** (real voice + tools), gives them **bounded independence**
(run whole campaigns unsupervised), and adds a **dashboard** to watch it all.
Decisions P2-D1…P2-D6 in `docs/decisions.md`.

Phase 2 is still **incremental, not a shipped product** (D0.1) — start of dev,
reshape after we see what works.

## Architecture in one picture

```
        AUTHORIZE                RUN (bounded autonomy)              WATCH
  human ──campaign──▶  Campaign Orchestrator ──dial──▶  Voice Runtime ──▶ lead
  (agent+leads+          (queue + per-lead state          (managed voice
   schedule+envelope)     in Postgres; kill switch)        platform + Gemini Live)
                              │                               │
                              │ in-call fast functions  ◀─────┘ (calendar, lookup)
                              ▼
                         Tool Registry  ◀── per-tenant OAuth connections
                         (curated, least-privilege, guardrailed params)
                              │ post-call
                              ▼
                         Async Workflows (n8n-style: email, CRM, follow-up)

  EVERY action emits ──▶  Event Stream  ──▶  { Dashboard | Auto-pause | Audit | Analytics }
                          (single source; immutable log = compliance proof)
```

Everything the agent does flows through the **tool registry** (guardrails live at
the tool boundary, D6/D-security) and emits to the **event stream** (P2-D5).

## New frozen contracts (critical path — freeze before fan-out)

| Contract | Defines |
|---|---|
| **Event schema** | The typed events every component emits/consumes. THE Phase-2 keystone — dashboard, auto-pause, audit, analytics all bind to it. |
| **Tool registry interface** | A registry tool: name, scopes, param JSON Schema, in-call vs post-call, baked-in guardrails. Plus the per-tenant connection/credential interface. |
| **Campaign + lead-lifecycle model** | Campaign object (agent, leads, schedule, envelope, state) and per-lead states (`queued → dialing → in-call → outcome → follow-up → done/retry`). |
| **Voice-runtime interface** | How the runtime loop starts/monitors/ends a call session and executes in-call functions — provider-agnostic so Retell→LiveKit is a swap (D9). |

These extend, not replace, the Phase-1 contracts. The agent config's `automation`
section now references tool-registry entries.

## Parallel workstreams (fan out after contracts freeze)

| # | Workstream | Responsibility | Depends on |
|---|---|---|---|
| P2-1 | **Voice runtime** | Managed voice platform + Gemini Live; execute in-call fast functions; escalation/warm-transfer. Thickens the Phase-1 runtime loop. | voice-runtime iface, tool registry |
| P2-2 | **Campaign orchestrator** | Queue + workers + per-lead state in Postgres; scheduling, rate/concurrency limits, calling-hours; the **kill-switch mechanism**. | campaign model, event schema |
| P2-3 | **Tool registry + integrations** | The catalog; per-tenant OAuth connections (encrypted, scoped); guardrailed tool execution. | tool registry iface |
| P2-4 | **Async workflows** | n8n-style post-call automations (email/CRM/follow-up sequences) driven off outcomes. | tool registry, event schema |
| P2-5 | **Event stream + observability backbone** | Event bus + persistence + immutable audit log + query/aggregation for analytics. | event schema |
| P2-6 | **Auto-pause / escalation engine** | Pattern detection over the event stream → trips the kill switch + fires escalations. | event schema, orchestrator kill-switch |
| P2-7 | **Dashboard frontend** | Fleet / campaign / live-call / audit views; kill-switch + emergency-stop controls; live via event-stream subscription. | event schema, orchestrator control API |

## Integration order (serial, like Phase 1)

Event stream (P2-5) and tool registry (P2-3) are foundational — most streams emit
to one and act through the other. Suggested merge order:

**P2-5 → P2-3 → P2-2 → P2-1 → {P2-4, P2-6} → P2-7**

Run E2E at each edge: one authorized campaign dials one test lead through the real
voice runtime, books via a connected calendar, emits the full event trail, honors a
mid-campaign pause, and shows correctly on the dashboard.

## Flagged defaults (react if you disagree — P2-D6)
- **Voice platform:** start on **Retell** (compliance-leaning: HIPAA/published
  pricing, relevant for DNC/disclosure), behind the voice-runtime interface; swap to
  **LiveKit** past ~10k min/month. Managed-first to get real calls fast.
- **Escalation:** **warm transfer-to-human** as a registry action, triggered when a
  lead asks for a human, the agent is low-confidence, or a guardrail edge is hit.
