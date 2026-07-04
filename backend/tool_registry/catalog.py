"""The curated catalog — the platform's entire capability surface (P2-D4).

This generalizes Phase-1's `backend/runtime_loop/tools.build_tools()` (which
hard-codes `if calendar.enabled -> book_meeting`) into data: a fixed list of
`RegistryTool`s. Curated, NOT self-serve — a new capability is a platform roadmap
item, which is exactly what keeps the registry a guardrail surface. Wishlist ->
registry "graduation" (D13/P2-D4) is literally appending an entry here.

Load-bearing invariants (D-security), enforced structurally in the param schemas:
  * **capability == an exposed function, nothing more.** There is no `offer_discount`,
    no free-composed URL, no arbitrary email body to expose at all.
  * **least-privilege params.** The model picks a time; it may NOT pick the calendar,
    the attendee identity, or the meeting length. It picks an APPROVED template id;
    it may NOT write a body or a link. Anything the handler must control is absent
    from the schema (`additionalProperties: false` seals it).

Keys match `automation` block names ("calendar", "email") so `config.automation`
references entries by name with no config-schema change (per the frozen contract).
`params` here is the STATIC least-privilege shape; per-agent values that narrow it
further (e.g. the concrete enum of approved template ids) are injected when the
registry is built for a given agent — see `registry.build_registry`.

`check_availability` is the one entry with no matching `automation` block of its
own — it's a read, gated on `automation.calendar.enabled` (same as `calendar`,
booking) rather than getting its own config toggle, since offering it without the
ability to book would be pointless.
"""

from __future__ import annotations

from contracts.tool_registry.interface import RegistryTool, Timing

# Provider identifiers — used to resolve the OAuth connection a tool runs against.
GOOGLE_CALENDAR = "google_calendar"
GMAIL = "gmail"

# Minimal OAuth scopes per provider (least-privilege at the connection layer too).
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
EMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


CALENDAR_TOOL = RegistryTool(
    name="calendar",  # matches config.automation.calendar (frozen contract)
    description=(
        "Hold a meeting slot on the lead's behalf on the connected calendar. "
        "Business hours, the booking window, and meeting length are enforced by the "
        "handler in code — you only propose a start time within the offered window. "
        "If you have the lead's email, pass it as attendee_email so the platform "
        "invites them on the event (this is how they actually receive an invite)."
    ),
    timing=Timing.IN_CALL,  # fast function the voice LLM calls live (D6)
    params={
        "type": "object",
        "properties": {
            "start_iso": {
                "type": "string",
                "description": (
                    "Proposed meeting start time, ISO-8601 with timezone offset "
                    "(e.g. 2026-07-06T15:00:00-04:00). Should be one of the slots "
                    "your availability tool returned."
                ),
            },
            "attendee_email": {
                "type": "string",
                "description": (
                    "The lead's REAL email address, spelled exactly as they gave it to "
                    "you on this call — used to invite them and to send their "
                    "confirmation. Never invent, guess, or substitute a placeholder or "
                    "example address (nothing @example.com). If you don't have their "
                    "actual address, ask for it or omit this field — do not make one up."
                ),
            },
        },
        "required": ["start_iso"],
        # Sealed: no way to smuggle calendar_ref or length. attendee_email is the one
        # least-privilege exception — it's a value the model already collected
        # verbally per the closing directions, not something it's choosing freely.
        "additionalProperties": False,
    },
    provider=GOOGLE_CALENDAR,
    required_scopes=CALENDAR_SCOPES,
)


CHECK_AVAILABILITY_TOOL = RegistryTool(
    name="check_availability",  # no matching automation block — gated on calendar.enabled
    description=(
        "Look up real open meeting slots on the connected calendar for a given day, "
        "so you can offer the lead a time that's actually free instead of guessing. "
        "Returns up to a handful of candidate start times within calling hours."
    ),
    timing=Timing.IN_CALL,
    params={
        "type": "object",
        "properties": {
            "date_iso": {
                "type": "string",
                "description": "The calendar date to check, as YYYY-MM-DD (e.g. 2026-07-06).",
            }
        },
        "required": ["date_iso"],
        "additionalProperties": False,
    },
    provider=GOOGLE_CALENDAR,
    required_scopes=CALENDAR_SCOPES,
)


EMAIL_TOOL = RegistryTool(
    name="email",  # matches config.automation.email (frozen contract)
    description=(
        "Send one of the pre-approved email templates to the lead. You choose only "
        "WHICH approved template — you cannot write the body or add any link. Every "
        "link is baked into the template and screened against the platform allowlist."
    ),
    timing=Timing.POST_CALL,  # async orchestration, latency-tolerant (D6)
    params={
        "type": "object",
        "properties": {
            "template_id": {
                "type": "string",
                # The concrete enum of approved ids is injected per-agent at
                # registry-build time. Empty allowlist -> enum [] -> no valid call
                # (structural denial), exactly as in Phase 1.
                "description": "Which approved template to send.",
            }
        },
        "required": ["template_id"],
        "additionalProperties": False,
    },
    provider=GMAIL,
    required_scopes=EMAIL_SCOPES,
)


# The whole catalog. Order is the display order; keys are unique by `name`.
DEFAULT_CATALOG: list[RegistryTool] = [CALENDAR_TOOL, CHECK_AVAILABILITY_TOOL, EMAIL_TOOL]
