"""capability follows connection — connecting a provider enables that capability on
the tenant's agents (the fix for a booking SDR that shipped with booking disabled and
no path to turn it on)."""

from __future__ import annotations

from backend.config_gate.repository import InMemoryConfigRepository
from backend.config_gate.service import AgentService
from backend.integration.capability_sync import enable_connected_capabilities


class _FakeConnections:
    """Minimal ConnectionStore stand-in: a set of (tenant, provider) that are connected."""

    def __init__(self, connected: set[tuple[str, str]]):
        self._connected = connected

    def for_provider(self, tenant_id: str, provider: str):
        return object() if (tenant_id, provider) in self._connected else None


TENANT = "user-1"


def _service_with_agent():
    service = AgentService(InMemoryConfigRepository())
    config = service.create_agent(TENANT, "Acme SDR")
    return service, config.meta.id


def test_connecting_calendar_enables_calendar_on_agents():
    service, agent_id = _service_with_agent()
    assert service.get_agent(agent_id, TENANT).automation.calendar.enabled is False

    conns = _FakeConnections({(TENANT, "google_calendar")})
    enable_connected_capabilities(service, conns, TENANT, provider="google_calendar")

    cfg = service.get_agent(agent_id, TENANT)
    assert cfg.automation.calendar.enabled is True
    assert cfg.automation.email.enabled is False  # untouched — email isn't connected


def test_reconcile_all_enables_every_connected_capability():
    service, agent_id = _service_with_agent()
    conns = _FakeConnections({(TENANT, "google_calendar"), (TENANT, "gmail")})

    enable_connected_capabilities(service, conns, TENANT)  # no provider -> reconcile all

    cfg = service.get_agent(agent_id, TENANT)
    assert cfg.automation.calendar.enabled is True
    assert cfg.automation.email.enabled is True


def test_enabling_email_seeds_a_default_template_so_it_can_actually_send():
    # An enabled-but-templateless email capability still can't send (the confirmation
    # resolves to no template) — so enabling seeds a default template id too.
    service, agent_id = _service_with_agent()
    assert service.get_agent(agent_id, TENANT).automation.email.template_ids == []

    conns = _FakeConnections({(TENANT, "gmail")})
    enable_connected_capabilities(service, conns, TENANT, provider="gmail")

    cfg = service.get_agent(agent_id, TENANT)
    assert cfg.automation.email.enabled is True
    assert cfg.automation.email.template_ids == ["booking_confirmation"]


def test_email_reconcile_does_not_clobber_a_user_chosen_template():
    service, agent_id = _service_with_agent()
    # user already picked their own template
    service.apply_patch(agent_id, TENANT, "automation.email.template_ids", ["intro"])

    conns = _FakeConnections({(TENANT, "gmail")})
    enable_connected_capabilities(service, conns, TENANT, provider="gmail")

    assert service.get_agent(agent_id, TENANT).automation.email.template_ids == ["intro"]


def test_never_enables_a_capability_whose_provider_is_not_connected():
    service, agent_id = _service_with_agent()
    conns = _FakeConnections(set())  # nothing connected

    enable_connected_capabilities(service, conns, TENANT)

    cfg = service.get_agent(agent_id, TENANT)
    assert cfg.automation.calendar.enabled is False
    assert cfg.automation.email.enabled is False


def test_idempotent_no_extra_version_bump_when_already_enabled():
    service, agent_id = _service_with_agent()
    conns = _FakeConnections({(TENANT, "google_calendar")})

    enable_connected_capabilities(service, conns, TENANT, provider="google_calendar")
    v1 = service.get_agent(agent_id, TENANT).meta.version
    enable_connected_capabilities(service, conns, TENANT, provider="google_calendar")
    v2 = service.get_agent(agent_id, TENANT).meta.version

    assert v1 == v2  # already on -> skipped, no redundant patch/version bump


def test_reconcile_spans_all_of_a_tenants_agents():
    service = AgentService(InMemoryConfigRepository())
    a = service.create_agent(TENANT, "Agent A").meta.id
    b = service.create_agent(TENANT, "Agent B").meta.id
    conns = _FakeConnections({(TENANT, "google_calendar")})

    enable_connected_capabilities(service, conns, TENANT, provider="google_calendar")

    assert service.get_agent(a, TENANT).automation.calendar.enabled is True
    assert service.get_agent(b, TENANT).automation.calendar.enabled is True
