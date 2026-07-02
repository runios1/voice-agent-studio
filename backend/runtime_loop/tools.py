"""The in-call function layer — where capability is DEFINED and, in Phase 2, where
in-call guardrails will be enforced (D6, this workstream's README).

The load-bearing rule (D-security): **capability == an exposed function, nothing
more.** A free-text config field can never grant a capability; only appearing here,
gated by an *enabled* automation block, does. So a disabled calendar produces no
`book_meeting` tool, and the agent physically cannot book — there is no function to
call. There is deliberately no `offer_discount` / arbitrary-URL / send-anywhere
function to expose at all.

Phase 1 is a TEXT PREVIEW with no real tools wired (see the README boundary), so
`build_tools()` returns [] by default. Set `include_declared=True` to materialize
the tool *definitions* for enabled automation — used to prove the structural claim
("no capability beyond what's declared and enabled") and as the Phase-2 seam. Even
then, parameter schemas are least-privilege: e.g. email takes an approved
`template_id`, never a free-composed URL or arbitrary body.
"""

from __future__ import annotations

from contracts.config_schema.schema import AgentConfig
from contracts.model_wrapper.interface import ToolDef


def build_tools(config: AgentConfig, *, include_declared: bool = False) -> list[ToolDef]:
    """Return the tools the runtime may expose for this config.

    Phase 1 default (`include_declared=False`): [] — no real tools in the preview.
    `include_declared=True`: the least-privilege ToolDefs for each ENABLED automation
    block only. Disabled or absent automation yields no tool (structural denial).
    """
    if not include_declared:
        return []

    tools: list[ToolDef] = []

    if config.automation.calendar.enabled:
        tools.append(
            ToolDef(
                name="book_meeting",
                description=(
                    "Hold a meeting slot on the connected calendar. Business hours "
                    "and booking window are enforced by the handler, not by you."
                ),
                # Least-privilege: the model picks a time; it cannot choose the
                # calendar, the attendee identity, or the meeting length.
                parameters={
                    "type": "object",
                    "properties": {
                        "start_iso": {
                            "type": "string",
                            "description": "Proposed start time, ISO-8601.",
                        }
                    },
                    "required": ["start_iso"],
                    "additionalProperties": False,
                },
            )
        )

    if config.automation.email.enabled:
        template_ids = config.automation.email.template_ids
        # The model may only choose from approved template ids — never compose a
        # body or a URL. Empty allowlist -> enum of [] -> no valid call (structural).
        tools.append(
            ToolDef(
                name="send_email",
                description=(
                    "Send one of the pre-approved email templates. You cannot write "
                    "the body or include any link that isn't already in the template."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "template_id": {
                            "type": "string",
                            "enum": list(template_ids),
                            "description": "Which approved template to send.",
                        }
                    },
                    "required": ["template_id"],
                    "additionalProperties": False,
                },
            )
        )

    return tools
