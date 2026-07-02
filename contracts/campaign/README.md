# campaign/ — campaign + lead-lifecycle model (Phase 2, FROZEN)

State the orchestrator (P2-2) persists in Postgres and the dashboard (P2-7) reads.
Bounded autonomy (P2-D1): a human authorizes a `Campaign` (agent + leads + schedule
+ `GuardrailEnvelope`); the agent runs it within that envelope. Per-lead state is
persisted (not in worker memory) so a crash resumes from the DB with no double-dial
(P2-D2). The envelope can only be equal-or-stricter than the locked guardrails.
