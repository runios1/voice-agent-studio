"""Per-agent guardrail policy — the values handlers enforce in code.

The frozen `ToolContext` deliberately carries only WHO and WHICH-connection, not the
agent config, so handlers don't get to pick their own limits. Instead the per-agent
guardrail *values* are distilled from an `AgentConfig` into this immutable
`GuardrailPolicy` and injected when the registry is built for that agent
(`registry.build_registry`). The handler then enforces them — this module is where
the guardrail numbers come from; `handlers.py` is where they bite.

What we pull from the config (single source of truth, D3):
  * calling hours          <- guardrails.calling_hours        (LOCKED)
  * allowed link domains   <- guardrails.allowed_link_domains (LOCKED)
  * booking window (days)  <- automation.calendar.booking_window_days
  * meeting length (min)   <- automation.calendar.meeting_length_minutes
  * approved template ids  <- automation.email.template_ids

Keeping this a plain derived value object (not the config itself) means a handler
literally cannot read anything it isn't handed — least context (D-security).
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

from contracts.config_schema.schema import AgentConfig
from backend.tool_registry.errors import GuardrailViolation

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - stdlib since 3.9; guard is belt-and-braces
    ZoneInfo = None  # type: ignore[assignment]

log = logging.getLogger("voice_agent_studio.tool_registry.guardrails")

# The platform's LOCAL timezone. calling_hours are `*_local` (per the schema) and a
# booked slot's wall-clock must match what the lead was told — but the code historically
# treated both as UTC, so on a UTC+n host every booking landed n hours off. This is the
# one place that resolves "local": an IANA name from PLATFORM_TIMEZONE, defaulting to
# Israel (the deployment's locale). ZoneInfo handles DST (IDT/IST) correctly.
_DEFAULT_PLATFORM_TZ = "Asia/Jerusalem"


def platform_tz():
    name = os.getenv("PLATFORM_TIMEZONE") or _DEFAULT_PLATFORM_TZ
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:  # bad name or missing tz database
            log.warning("PLATFORM_TIMEZONE %r unavailable; falling back to UTC", name)
    return timezone.utc

# Deliberately loose — this rejects obviously-malformed input, not RFC 5322
# compliance. Real deliverability is the provider's problem, not a guardrail's.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Reserved / documentation domains (RFC 2606 & 6761) — never real inboxes. A voice
# model, asked to record an address it heard, will routinely substitute one of these
# as a placeholder; sending a real lead's confirmation to `someone@example.com` is a
# correctness/privacy bug, so we reject them structurally rather than hoping the prompt
# holds. Matches the exact reserved second-level domains and the reserved TLDs.
_RESERVED_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "example.edu"}
_RESERVED_EMAIL_TLDS = {"test", "example", "invalid", "localhost"}


def _is_placeholder_email_domain(domain: str) -> bool:
    domain = domain.strip().lower().rstrip(".")
    if domain in _RESERVED_EMAIL_DOMAINS:
        return True
    tld = domain.rsplit(".", 1)[-1] if "." in domain else domain
    return tld in _RESERVED_EMAIL_TLDS


@dataclass(frozen=True)
class GuardrailPolicy:
    calling_hours_start: int = 8
    calling_hours_end: int = 20
    allowed_link_domains: tuple[str, ...] = ()
    booking_window_days: int = 14
    meeting_length_minutes: int = 30
    approved_template_ids: tuple[str, ...] = ()

    @classmethod
    def from_config(cls, config: AgentConfig) -> "GuardrailPolicy":
        g = config.guardrails
        cal = config.automation.calendar
        email = config.automation.email
        return cls(
            calling_hours_start=g.calling_hours.start_hour_local,
            calling_hours_end=g.calling_hours.end_hour_local,
            allowed_link_domains=tuple(g.allowed_link_domains),
            booking_window_days=cal.booking_window_days,
            meeting_length_minutes=cal.meeting_length_minutes,
            approved_template_ids=tuple(email.template_ids),
        )


# --------------------------------------------------------------------------- #
# Enforcement helpers — raise GuardrailViolation on a breach. Each one is the
# in-code wall for a specific guardrail (D6). Handlers call these before acting.
# --------------------------------------------------------------------------- #
def check_within_calling_hours(
    start: datetime, policy: GuardrailPolicy, *, tool: str
) -> None:
    """Reject a slot whose LOCAL hour falls outside the platform calling window.

    The guardrail is on the wall-clock hour the lead experiences, so an aware `start`
    is converted to the platform's local timezone first (a slot sent as UTC or any
    other offset is judged by its LOCAL hour, not the raw one). Half-open
    [start_hour, end_hour): a slot at exactly end_hour is already out of hours.
    """
    local = start.astimezone(platform_tz()) if start.tzinfo is not None else start
    hour = local.hour
    if hour < policy.calling_hours_start or hour >= policy.calling_hours_end:
        raise GuardrailViolation(
            (
                f"That time is outside allowed calling hours "
                f"({policy.calling_hours_start:02d}:00–{policy.calling_hours_end:02d}:00 local)."
            ),
            tool=tool,
            param="start_iso",
        )


def check_within_booking_window(
    start: datetime, now: datetime, policy: GuardrailPolicy, *, tool: str
) -> None:
    """Reject a slot in the past or beyond the configured booking window."""
    delta_days = (start - now).total_seconds() / 86400.0
    if delta_days < 0:
        raise GuardrailViolation(
            "That time is in the past.", tool=tool, param="start_iso"
        )
    if delta_days > policy.booking_window_days:
        raise GuardrailViolation(
            f"That time is beyond the {policy.booking_window_days}-day booking window.",
            tool=tool,
            param="start_iso",
        )


def _registrable_domain(host: str) -> str:
    return host.lower().lstrip(".")


def check_domain_allowlisted(url: str, policy: GuardrailPolicy, *, tool: str) -> None:
    """Reject a URL whose host is not on the platform allowlist. A domain matches if
    it equals an allowlisted domain or is a subdomain of one. Empty allowlist means
    NO link may appear (structural: nothing can match)."""
    host = _registrable_domain(urlparse(url).hostname or "")
    if not host:
        raise GuardrailViolation(
            "A link was malformed or had no host.", tool=tool, param="link"
        )
    for allowed in policy.allowed_link_domains:
        a = _registrable_domain(allowed)
        if host == a or host.endswith("." + a):
            return
    raise GuardrailViolation(
        f"Link domain '{host}' is not on the platform allowlist.",
        tool=tool,
        param="link",
    )


def check_template_approved(
    template_id: str, policy: GuardrailPolicy, *, tool: str
) -> None:
    """Reject a template id the agent wasn't configured to send."""
    if template_id not in policy.approved_template_ids:
        raise GuardrailViolation(
            "That email template is not approved for this agent.",
            tool=tool,
            param="template_id",
        )


def check_valid_email(value: str, policy: GuardrailPolicy, *, tool: str) -> None:
    """Reject a malformed email address. Not a business guardrail (no policy value
    is consulted) — just rejecting obviously-bad input before it reaches a provider
    call, same shape as the other checks so handlers have one failure pattern."""
    if not isinstance(value, str) or not _EMAIL_RE.match(value):
        raise GuardrailViolation(
            "That doesn't look like a valid email address.",
            tool=tool,
            param="attendee_email",
        )
    if _is_placeholder_email_domain(value.rsplit("@", 1)[-1]):
        raise GuardrailViolation(
            "That looks like a placeholder/example address, not the lead's real email. "
            "Use the exact address they gave you.",
            tool=tool,
            param="attendee_email",
        )
