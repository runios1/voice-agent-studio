"""P2-2 — Campaign orchestrator.

Bounded-autonomy execution (P2-D1): a human authorizes a Campaign (agent + leads +
schedule + guardrail envelope); this package then dials the leads unsupervised
within that envelope, delegating each call to the VoiceRuntime (P2-1) and emitting
lifecycle Events (P2-5), with a kill switch (P2-D3) able to halt new dials at any
time. Per-lead state is persisted (P2-D2) so a crash resumes from the DB with no
double-dial.

The queue is the persisted `leads` table itself (state + `next_action_at`), not an
external broker — the leanest shape that satisfies "queue + per-lead state in
Postgres" and stays swappable behind `OrchestratorRepository`.
"""

from __future__ import annotations

from backend.orchestrator.service import OrchestratorService

__all__ = ["OrchestratorService"]
