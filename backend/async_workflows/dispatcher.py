"""The event-driven entry point.

The runner subscribes to the event stream and reacts to `lead.outcome` events —
the architecture routes everything through the stream (P2-D5) rather than having the
orchestrator call us directly. This keeps P2-4 a pure consumer: give it an outcome
event, it routes the outcome to a workflow and runs it. Anything that isn't a
`lead.outcome` (or has no route) is ignored, not errored.

The originating event's `event_id` becomes the run's idempotency root, so the whole
pipeline — dispatch + every step — is replay-safe on redelivery.
"""

from __future__ import annotations

from contracts.events.schema import Event, EventType

from .engine import WorkflowEngine
from .models import RoutingTable, Trigger, WorkflowRun


class WorkflowDispatcher:
    def __init__(self, *, engine: WorkflowEngine, routing: RoutingTable) -> None:
        self._engine = engine
        self._routing = routing

    async def handle(self, event: Event) -> WorkflowRun | None:
        if event.type is not EventType.LEAD_OUTCOME:
            return None

        outcome = event.payload.get("outcome")
        workflow_name = self._routing.workflow_for(outcome)
        if workflow_name is None:
            return None

        trigger = Trigger(
            run_id=event.event_id,
            tenant_id=event.tenant_id,
            campaign_id=event.campaign_id,
            lead_id=event.lead_id,
            agent_id=event.agent_id,
            call_id=event.call_id,
            payload=dict(event.payload),
        )
        return await self._engine.run(workflow_name, trigger)
