"""Engine invariants: guardrail enforcement, tenant-scoped context, unknown workflow."""

from __future__ import annotations

import pytest

from contracts.tool_registry.interface import ToolContext

from backend.async_workflows.clock import ManualClock
from backend.async_workflows.defaults import default_library
from backend.async_workflows.engine import LocalWorkflowEngine
from backend.async_workflows.idempotency import InMemoryRunLedger
from backend.async_workflows.mocks import (
    APPROVED_EMAIL_TEMPLATES,
    InMemoryEventSink,
    MockConnectionResolver,
    MockToolRegistry,
)
from backend.async_workflows.models import Step, StepKind, Trigger, Workflow, WorkflowLibrary
from backend.async_workflows.scheduler import FollowupScheduler


def _engine(library, *, clock=None):
    clock = clock or ManualClock()
    return LocalWorkflowEngine(
        library=library,
        registry=MockToolRegistry(),
        ledger=InMemoryRunLedger(),
        sink=InMemoryEventSink(),
        scheduler=FollowupScheduler(clock),
        clock=clock,
        connections=MockConnectionResolver(),
    )


async def test_unapproved_template_is_rejected_by_handler():
    # An unapproved template id must never send — guardrail is in the handler (code).
    bad = WorkflowLibrary([
        Workflow("bad", (Step(StepKind.TOOL, tool="email", args={"template_id": "phish"}),)),
    ])
    assert "phish" not in APPROVED_EMAIL_TEMPLATES
    engine = _engine(bad)
    with pytest.raises(ValueError):
        await engine.run("bad", Trigger(run_id="r", tenant_id="t"))


async def test_unknown_workflow_is_a_noop_not_a_crash():
    engine = _engine(default_library())
    run = await engine.run("does_not_exist", Trigger(run_id="r", tenant_id="t"))
    assert run.steps == []


async def test_handler_receives_tenant_scoped_context_and_connection():
    seen: list[ToolContext] = []

    class SpyRegistry(MockToolRegistry):
        def handler_for(self, name):
            handler = super().handler_for(name)
            orig = handler.execute

            async def wrapped(args, ctx: ToolContext):
                seen.append(ctx)
                return await orig(args, ctx)

            handler.execute = wrapped  # type: ignore[method-assign]
            return handler

    clock = ManualClock()
    engine = LocalWorkflowEngine(
        library=default_library(),
        registry=SpyRegistry(),
        ledger=InMemoryRunLedger(),
        sink=InMemoryEventSink(),
        scheduler=FollowupScheduler(clock),
        clock=clock,
        connections=MockConnectionResolver(),
    )
    await engine.run(
        "booking_confirmation",
        Trigger(run_id="r", tenant_id="tenant-9", campaign_id="c", lead_id="l"),
    )
    # every handler saw the caller's tenant, never picked its own
    assert all(ctx.tenant_id == "tenant-9" for ctx in seen)
    # a per-tenant connection was resolved and scoped to that tenant, per provider
    providers = {ctx.connection.provider: ctx.connection for ctx in seen if ctx.connection}
    assert providers["gmail"].tenant_id == "tenant-9"
    assert providers["salesforce"].tenant_id == "tenant-9"
