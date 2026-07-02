"""Workflow definitions — the declarative post-call automation shapes.

A workflow is DATA: an ordered list of steps. That's the whole point of P2-D2's
"n8n-style" engine choice — automations are describable/auditable structures, not
imperative code, so a durable engine (Temporal/n8n) can execute the same
definitions later without a rewrite of callers.

Two boundaries live in these shapes (this stream's README):
  * a TOOL step names a POST_CALL registry tool and passes least-privilege args —
    for email that means an approved `template_id`, NEVER a composed body/URL. This
    module cannot express "send arbitrary text"; there is no field for it.
  * a SCHEDULE step defers a *touch* (a follow-up email), not a re-dial. Re-dialing
    a lead is the orchestrator's job (LeadState.RETRY); we only schedule touches.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class StepKind(str, Enum):
    TOOL = "tool"                    # invoke one POST_CALL registry tool
    SCHEDULE = "schedule"            # defer another workflow to run after a delay


@dataclass(frozen=True)
class Step:
    kind: StepKind

    # --- TOOL step ---
    tool: Optional[str] = None       # registry tool name (matches an automation block)
    args: dict[str, Any] = field(default_factory=dict)  # least-privilege args only

    # --- SCHEDULE step ---
    followup_workflow: Optional[str] = None   # workflow to run when the timer fires
    delay_seconds: Optional[int] = None       # fixed delay; ignored if `backoff`
    backoff: bool = False                     # compute the delay from lead `attempts`
    respect_max_attempts: bool = True         # stop scheduling once attempts exhausted

    def __post_init__(self) -> None:
        if self.kind is StepKind.TOOL and not self.tool:
            raise ValueError("TOOL step requires `tool`")
        if self.kind is StepKind.SCHEDULE and not self.followup_workflow:
            raise ValueError("SCHEDULE step requires `followup_workflow`")


@dataclass(frozen=True)
class Workflow:
    name: str
    steps: tuple[Step, ...]


class WorkflowLibrary:
    """The named catalog of workflows the engine can run. Platform-authored (like the
    tool registry): a workflow references approved templates + registry tools, so the
    set of automations a tenant can trigger is curated, not free-form."""

    def __init__(self, workflows: list[Workflow]) -> None:
        self._by_name = {w.name: w for w in workflows}

    def get(self, name: str) -> Optional[Workflow]:
        return self._by_name.get(name)

    def names(self) -> list[str]:
        return list(self._by_name)


class RoutingTable:
    """Maps a call OUTCOME (`lead.outcome` payload) to the workflow it triggers.
    An unrouted outcome is a no-op, not an error — most outcomes do nothing post-call."""

    def __init__(self, routes: dict[str, str]) -> None:
        self._routes = dict(routes)

    def workflow_for(self, outcome: Optional[str]) -> Optional[str]:
        if outcome is None:
            return None
        return self._routes.get(outcome)


@dataclass
class Trigger:
    """What kicks off a workflow run, decoupled from any concrete Event type so the
    engine serves both outcome-driven runs (root = the outcome `event_id`) and
    scheduler-driven follow-ups (root = the scheduled action id). `run_id` is the
    idempotency root: every side-effect key in the run derives from it (see
    idempotency.py), so replaying the same trigger touches the same keys and no-ops."""

    run_id: str
    tenant_id: str
    campaign_id: Optional[str] = None
    lead_id: Optional[str] = None
    agent_id: Optional[str] = None
    call_id: Optional[str] = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepResult:
    step_index: int
    kind: StepKind
    action: str                      # "invoked" | "skipped_duplicate" | "scheduled"
                                     #  | "skipped_exhausted"
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowRun:
    workflow: str
    run_id: str
    steps: list[StepResult] = field(default_factory=list)


@dataclass(frozen=True)
class ScheduledAction:
    """A deferred follow-up touch sitting in the scheduler until `run_at`. `id` is
    DETERMINISTIC (derived from the originating run) so re-processing the same
    outcome enqueues the same id and the scheduler dedupes it — no duplicate timers."""

    id: str
    run_at: datetime
    workflow: str
    trigger: Trigger
