"""Capability follows connection — the missing link that made booking/email silently
inert.

The problem this fixes: an agent's `automation.calendar.enabled` / `automation.email.
enabled` flags are the real capability gate (they declare the calendar/email tools to
the runtime and tell the agent it can act). But they default OFF, and *connecting* the
underlying Google account — the thing a user does expecting the agent to be able to
book — did nothing to them. So a user could connect their calendar, build a "book a
meeting" SDR, and the agent would still truthfully say it has no calendar access,
because the per-agent flag was never turned on and nothing ever turned it on.

The rule here: **when a tenant has a provider connected, that capability is enabled on
their agents.** We only ever enable a capability whose connection actually exists — so
we never make an agent claim something the runtime can't honor (the same "capability ==
an exposed function" posture, D-security). Reconciled at two moments:

  * on connect  — the user just linked Google Calendar → enable calendar on their
    agents immediately (the exact flow a user expects to "just work").
  * on login    — self-heals agents that were built before this existed, and covers
    platform-level providers (email) whose connection is seeded at login rather than
    via an explicit OAuth click.

Idempotent and defensive: an agent already enabled is skipped, and a failure on one
agent never breaks the login/connect it rides on (it's a convenience, not the gate).
"""

from __future__ import annotations

import logging
from typing import Optional, Protocol

log = logging.getLogger("voice_agent_studio.integration.capability_sync")

# The providers whose connection unlocks a capability (see backend/tool_registry/catalog.py).
KNOWN_PROVIDERS = ("google_calendar", "gmail")

# Seeded into automation.email.template_ids when a tenant enables email but has no
# templates yet — otherwise "enabled email" still can't send (the confirmation resolves
# to no template). Must exist in the email client's catalog (see resend_email.py /
# providers.build_email_client). `booking_confirmation` has no links, so it clears the
# link allowlist with no per-agent domain config.
DEFAULT_EMAIL_TEMPLATE_IDS = ["booking_confirmation"]


class _Connections(Protocol):
    def for_provider(self, tenant_id: str, provider: str): ...


class _Service(Protocol):
    def list_agents(self, owner_user_id: str): ...
    def get_agent(self, agent_id: str, owner_user_id: str): ...
    def apply_patch(self, agent_id: str, owner_user_id: str, path: str, value, expected_version=None): ...


def _needed_patches(provider: str, config) -> list[tuple[str, object]]:
    """The (path, value) patches that make `provider`'s capability enabled AND usable on
    this config — empty if it's already fully set up. Enabling email also seeds a default
    template so the capability can actually send, not just claim to."""
    patches: list[tuple[str, object]] = []
    if provider == "google_calendar":
        if not config.automation.calendar.enabled:
            patches.append(("automation.calendar.enabled", True))
    elif provider == "gmail":
        if not config.automation.email.enabled:
            patches.append(("automation.email.enabled", True))
        if not config.automation.email.template_ids:
            patches.append(
                ("automation.email.template_ids", list(DEFAULT_EMAIL_TEMPLATE_IDS))
            )
    return patches


def enable_connected_capabilities(
    service: _Service,
    connections: _Connections,
    tenant_id: str,
    *,
    provider: Optional[str] = None,
) -> None:
    """Ensure every capability whose provider the tenant has connected is enabled on
    all of that tenant's agents.

    `provider` limits it to one provider (used by the connect callback — we know
    exactly what was just linked); omitted reconciles every known provider (used at
    login). Never raises: a hiccup enabling one agent must not fail the login/connect.
    """
    providers = [provider] if provider is not None else list(KNOWN_PROVIDERS)
    for prov in providers:
        if prov not in KNOWN_PROVIDERS:
            continue
        # Capability follows connection: nothing to enable if it isn't connected.
        if connections.for_provider(tenant_id, prov) is None:
            continue
        try:
            agents = service.list_agents(tenant_id)
        except Exception:  # pragma: no cover - defensive; a read failure isn't fatal
            log.exception("capability_sync: could not list agents for %s", tenant_id)
            continue
        for meta in agents:
            try:
                config = service.get_agent(meta.id, tenant_id)
                for path, value in _needed_patches(prov, config):
                    service.apply_patch(meta.id, tenant_id, path, value)
                    log.info("capability_sync: set %s on agent %s", path, meta.id)
            except Exception:
                # One agent failing (locked/validation/not-found race) must not break
                # the whole reconcile or the login/connect it rides on.
                log.exception(
                    "capability_sync: failed to reconcile %s on agent %s", prov, meta.id
                )
