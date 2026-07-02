"""The platform-authored default automations: which outcome triggers what, and the
workflows themselves.

These are DATA (P2-D2). Everything an outcome can trigger is here, curated — like the
tool registry, the set of post-call automations is a roadmap surface, not free-form.
Email steps carry only an approved `template_id`; there is no body/URL to compose
(README boundary). Tool names ("email", "crm") match automation-block / registry
names so no config-schema change is needed.
"""

from __future__ import annotations

from .models import RoutingTable, Step, StepKind, Workflow, WorkflowLibrary

# Outcome -> workflow. Outcomes are the `lead.outcome` payload values the voice
# runtime records. Unlisted outcomes (e.g. "not_qualified") intentionally do nothing.
DEFAULT_ROUTES = {
    "booked": "booking_confirmation",
    "qualified": "qualified_nurture",
    "no_answer": "no_answer_followup",
    "voicemail": "no_answer_followup",
    "opted_out": "opt_out_record",
}


def default_library() -> WorkflowLibrary:
    return WorkflowLibrary(
        [
            # Meeting booked: confirm to the lead, then record it in CRM.
            Workflow(
                name="booking_confirmation",
                steps=(
                    Step(StepKind.TOOL, tool="email", args={"template_id": "booking_confirmation"}),
                    Step(StepKind.TOOL, tool="crm", args={"status": "meeting_booked"}),
                ),
            ),
            # Qualified but not booked: log to CRM, then a nudge touch a day later.
            Workflow(
                name="qualified_nurture",
                steps=(
                    Step(StepKind.TOOL, tool="crm", args={"status": "qualified"}),
                    Step(
                        StepKind.SCHEDULE,
                        followup_workflow="nurture_touch",
                        delay_seconds=86400,
                        respect_max_attempts=False,   # nurture isn't attempt-bounded
                    ),
                ),
            ),
            Workflow(
                name="nurture_touch",
                steps=(Step(StepKind.TOOL, tool="email", args={"template_id": "nurture_nudge"}),),
            ),
            # No answer / voicemail: schedule a follow-up touch with backoff, until the
            # lead's attempts are exhausted (re-dialing is the orchestrator's job).
            Workflow(
                name="no_answer_followup",
                steps=(
                    Step(
                        StepKind.SCHEDULE,
                        followup_workflow="no_answer_touch",
                        backoff=True,
                        respect_max_attempts=True,
                    ),
                ),
            ),
            Workflow(
                name="no_answer_touch",
                steps=(Step(StepKind.TOOL, tool="email", args={"template_id": "sorry_we_missed_you"}),),
            ),
            # Opt-out: record it; never email an opted-out lead.
            Workflow(
                name="opt_out_record",
                steps=(Step(StepKind.TOOL, tool="crm", args={"status": "opted_out"}),),
            ),
        ]
    )


def default_routing() -> RoutingTable:
    return RoutingTable(DEFAULT_ROUTES)
