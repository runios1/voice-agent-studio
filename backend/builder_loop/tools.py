"""The structured tool-calls the builder LLM may emit.

Patches, not whole-config regeneration (D5). Schema-constrained tool-calling makes
malformed output structurally impossible at the source (D-reliability): the model
can only ever propose a well-formed call, and the gate validates the rest.

Granularity (decided in the WS3 grill): a generic `set_field` for scalar/leaf
values, dedicated `add_*` helpers for list items (so appends don't require the
model to restate whole lists), `push_to_wishlist` for the four-way triage's
"capability we don't offer" bucket (D13), and `clear_field` to remove a value.

Each call maps to exactly one gate patch (list-append helpers read-modify-write
the whole list through the gate — see loop.py).
"""

from __future__ import annotations

from contracts.model_wrapper.interface import ToolDef

SET_FIELD = "set_field"
ADD_OBJECTION = "add_objection"
ADD_QUALIFICATION_CRITERION = "add_qualification_criterion"
PUSH_TO_WISHLIST = "push_to_wishlist"
CLEAR_FIELD = "clear_field"


BUILDER_TOOLS: list[ToolDef] = [
    ToolDef(
        name=SET_FIELD,
        description=(
            "Record a single answer by setting one config field. Use for scalar/leaf "
            "values (role, tone, opening, primary_objective, voicemail.action, "
            "persona.style_notes, custom_instructions, etc.). `path` is a dotted path "
            "into the agent config; `value` is the new value. Do NOT use for locked "
            "platform guardrails — they will be rejected."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Dotted config path, e.g. 'conversation.persona.tone'.",
                },
                "value": {
                    "description": "The value to set (string/number/boolean).",
                },
            },
            "required": ["path", "value"],
        },
    ),
    ToolDef(
        name=ADD_QUALIFICATION_CRITERION,
        description=(
            "Add one lead-qualification criterion (a question the agent asks to "
            "qualify a lead). Appends to conversation.qualification.criteria."
        ),
        parameters={
            "type": "object",
            "properties": {
                "label": {"type": "string", "description": "Short name, e.g. 'budget'."},
                "question": {
                    "type": "string",
                    "description": "The question the agent asks, if any.",
                },
                "disqualifying": {
                    "type": "boolean",
                    "description": "True if a bad answer disqualifies the lead.",
                },
            },
            "required": ["label"],
        },
    ),
    ToolDef(
        name=ADD_OBJECTION,
        description=(
            "Add one objection-handling entry: what the lead might say and how the "
            "agent should respond. Appends to conversation.objections."
        ),
        parameters={
            "type": "object",
            "properties": {
                "trigger": {
                    "type": "string",
                    "description": "What the lead says, e.g. 'it's too expensive'.",
                },
                "response_guidance": {
                    "type": "string",
                    "description": "How the agent should respond (free-text guidance).",
                },
            },
            "required": ["trigger", "response_guidance"],
        },
    ),
    ToolDef(
        name=PUSH_TO_WISHLIST,
        description=(
            "Record a capability the user asked for that this platform does NOT offer "
            "yet (e.g. send SMS, make payments, integrate an unsupported system). This "
            "acknowledges the request but QUARANTINES it: it never becomes something "
            "the agent acts on or promises. Use this instead of inventing a field."
        ),
        parameters={
            "type": "object",
            "properties": {
                "item": {
                    "type": "string",
                    "description": "The unsupported capability, in the user's words.",
                }
            },
            "required": ["item"],
        },
    ),
    ToolDef(
        name=CLEAR_FIELD,
        description="Clear a previously set field (set it back to empty).",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Dotted config path to clear."}
            },
            "required": ["path"],
        },
    ),
]
