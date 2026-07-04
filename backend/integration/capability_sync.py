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

# provider id (see backend/tool_registry/catalog.py) -> the capability flag it gates.
PROVIDER_TO_FLAG: dict[str, str] = {
    "google_calendar": "automation.calendar.enabled",
    "gmail": "automation.email.enabled",
}


class _Connections(Protocol):
    def for_provider(self, tenant_id: str, provider: str): ...


class _Service(Protocol):
    def list_agents(self, owner_user_id: str): ...
    def get_agent(self, agent_id: str, owner_user_id: str): ...
    def apply_patch(self, agent_id: str, owner_user_id: str, path: str, value, expected_version=None): ...


def _flag_value(config, flag: str) -> bool:
    """Read a dotted automation flag off a config object (attribute walk, not model_dump
    — cheaper and the paths are fixed)."""
    cur = config
    for part in flag.split("."):
        cur = getattr(cur, part)
    return bool(cur)


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
    providers = [provider] if provider is not None else list(PROVIDER_TO_FLAG)
    for prov in providers:
        flag = PROVIDER_TO_FLAG.get(prov)
        if flag is None:
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
                if _flag_value(config, flag):
                    continue  # already on — idempotent
                service.apply_patch(meta.id, tenant_id, flag, True)
                log.info("capability_sync: enabled %s on agent %s", flag, meta.id)
            except Exception:
                # One agent failing (locked/validation/not-found race) must not break
                # the whole reconcile or the login/connect it rides on.
                log.exception(
                    "capability_sync: failed to enable %s on agent %s", flag, meta.id
                )
