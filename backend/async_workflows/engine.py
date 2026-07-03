"""The workflow engine — executes a workflow's steps against the tool registry.

`WorkflowEngine` is the interface P2-D2 promised: a self-built local runner today,
swappable for a durable engine (Temporal/n8n) later without touching the dispatcher
or scheduler. `LocalWorkflowEngine` is that runner.

Every side effect is fenced by the idempotency ledger (replay-safe) and mirrored to
the event stream. The engine NEVER composes an email body or a URL and never picks a
tenant — it passes the workflow's approved args to a registry handler, which is where
guardrails are enforced in code (D6/D-security). Connections are resolved per tenant
by an injected resolver; the engine can't reach another tenant's credentials.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional, Protocol

from contracts.tool_registry.interface import Connection, ToolContext, ToolRegistry

from .backoff import attempts_exhausted, backoff_seconds
from .clock import Clock
from .events_out import EventSink, followup_scheduled_event, tool_invoked_event
from .idempotency import RunLedger, step_key
from .models import (
    ScheduledAction,
    Step,
    StepKind,
    StepResult,
    Trigger,
    Workflow,
    WorkflowLibrary,
    WorkflowRun,
)
from .scheduler import FollowupScheduler


class ConnectionResolver(Protocol):
    """Resolves the per-tenant OAuth connection a POST_CALL tool needs. The real one
    (P2-3) enforces that a tenant only ever reaches its own connections."""

    async def resolve(self, tenant_id: str, provider: str) -> Optional[Connection]: ...


class WorkflowEngine(Protocol):
    async def run(self, workflow_name: str, trigger: Trigger) -> WorkflowRun: ...


class LocalWorkflowEngine:
    def __init__(
        self,
        *,
        library: WorkflowLibrary,
        registry: ToolRegistry,
        ledger: RunLedger,
        sink: EventSink,
        scheduler: FollowupScheduler,
        clock: Clock,
        connections: ConnectionResolver,
        max_attempts: Optional[int] = None,
    ) -> None:
        self._library = library
        self._registry = registry
        self._ledger = ledger
        self._sink = sink
        self._scheduler = scheduler
        self._clock = clock
        self._connections = connections
        self._max_attempts = max_attempts

    async def run(self, workflow_name: str, trigger: Trigger) -> WorkflowRun:
        run = WorkflowRun(workflow=workflow_name, run_id=trigger.run_id)
        workflow = self._library.get(workflow_name)
        if workflow is None:
            # Unknown workflow: a no-op, not a crash (D-reliability — never a trace).
            return run

        for i, step in enumerate(workflow.steps):
            if step.kind is StepKind.TOOL:
                run.steps.append(await self._run_tool(trigger, i, step, workflow))
            else:
                run.steps.append(await self._run_schedule(trigger, i, step, workflow))
        return run

    # --- TOOL step ---------------------------------------------------------
    async def _run_tool(
        self, trigger: Trigger, index: int, step: Step, workflow: Workflow
    ) -> StepResult:
        assert step.tool is not None
        key = step_key(trigger.run_id, index, step.tool)
        if not await self._ledger.check_and_record(key):
            # Replay of an already-sent effect — the whole point of the ledger.
            return StepResult(index, StepKind.TOOL, "skipped_duplicate", {"tool": step.tool})

        tool = self._registry.get(step.tool)
        connection = None
        if tool is not None and tool.provider:
            connection = await self._connections.resolve(trigger.tenant_id, tool.provider)

        ctx = ToolContext(
            tenant_id=trigger.tenant_id,
            campaign_id=trigger.campaign_id,
            lead_id=trigger.lead_id,
            connection=connection,
        )
        handler = self._registry.handler_for(step.tool)
        result = await handler.execute(dict(step.args), ctx)

        await self._sink.emit(
            tool_invoked_event(
                trigger,
                self._clock.now(),
                tool=step.tool,
                args=dict(step.args),
                result=result,
                workflow=workflow.name,
            )
        )
        return StepResult(index, StepKind.TOOL, "invoked", {"tool": step.tool, "result": result})

    # --- SCHEDULE step -----------------------------------------------------
    async def _run_schedule(
        self, trigger: Trigger, index: int, step: Step, workflow: Workflow
    ) -> StepResult:
        assert step.followup_workflow is not None
        attempts = int(trigger.payload.get("attempts", 0))

        if step.respect_max_attempts:
            max_attempts = self._effective_max_attempts(trigger)
            if attempts_exhausted(attempts, max_attempts):
                # Cadence is spent — the orchestrator, not us, decides re-dials.
                return StepResult(
                    index, StepKind.SCHEDULE, "skipped_exhausted",
                    {"attempts": attempts, "max_attempts": max_attempts},
                )

        # Fence the schedule too, so a replay neither double-enqueues nor
        # double-emits `followup.scheduled`.
        action_id = step_key(trigger.run_id, index, step.followup_workflow)
        if not await self._ledger.check_and_record(action_id):
            return StepResult(
                index, StepKind.SCHEDULE, "skipped_duplicate",
                {"followup_workflow": step.followup_workflow},
            )

        delay = backoff_seconds(attempts) if step.backoff else int(step.delay_seconds or 0)
        run_at = self._clock.now() + timedelta(seconds=delay)

        child = Trigger(
            run_id=action_id,
            tenant_id=trigger.tenant_id,
            campaign_id=trigger.campaign_id,
            lead_id=trigger.lead_id,
            agent_id=trigger.agent_id,
            call_id=trigger.call_id,
            payload=dict(trigger.payload),
        )
        action = ScheduledAction(
            id=action_id, run_at=run_at, workflow=step.followup_workflow, trigger=child
        )
        await self._scheduler.schedule(action)

        await self._sink.emit(
            followup_scheduled_event(
                trigger,
                self._clock.now(),
                workflow=step.followup_workflow,
                scheduled_action_id=action_id,
                run_at=run_at,
            )
        )
        return StepResult(
            index, StepKind.SCHEDULE, "scheduled",
            {"followup_workflow": step.followup_workflow, "run_at": run_at.isoformat()},
        )

    def _effective_max_attempts(self, trigger: Trigger) -> int:
        override = trigger.payload.get("max_attempts")
        if override is not None:
            return int(override)
        if self._max_attempts is not None:
            return self._max_attempts
        from contracts.campaign.model import GuardrailEnvelope

        return GuardrailEnvelope().max_attempts_per_lead
