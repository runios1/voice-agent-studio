"""The catalog is the platform's whole capability surface — assert its shape."""

from __future__ import annotations

from contracts.tool_registry.interface import Timing
from backend.tool_registry.catalog import DEFAULT_CATALOG


def test_catalog_has_calendar_and_email():
    names = {t.name for t in DEFAULT_CATALOG}
    assert {"calendar", "email"} <= names


def test_names_match_automation_block_names():
    # The frozen contract: keys match `config.automation` block names, so no
    # config-schema change is needed to reference a tool.
    for t in DEFAULT_CATALOG:
        assert t.name in {"calendar", "email"}


def test_timings():
    by_name = {t.name: t for t in DEFAULT_CATALOG}
    assert by_name["calendar"].timing == Timing.IN_CALL   # fast live function
    assert by_name["email"].timing == Timing.POST_CALL     # async orchestration


def test_params_are_least_privilege_and_sealed():
    # No tool may accept a free-composed URL / body / arbitrary field, and every
    # schema seals extra properties (structural denial, D-security).
    for t in DEFAULT_CATALOG:
        assert t.params.get("additionalProperties") is False
        props = t.params.get("properties", {})
        assert "url" not in props and "body" not in props and "link" not in props


def test_calendar_only_exposes_start_time():
    cal = next(t for t in DEFAULT_CATALOG if t.name == "calendar")
    # The model picks a time and nothing else — not the calendar, attendee, or length.
    assert set(cal.params["properties"]) == {"start_iso"}


def test_email_only_exposes_template_id():
    email = next(t for t in DEFAULT_CATALOG if t.name == "email")
    assert set(email.params["properties"]) == {"template_id"}


def test_providers_and_scopes_present():
    for t in DEFAULT_CATALOG:
        assert t.provider  # every catalog tool runs against a per-tenant connection
        assert t.required_scopes


def test_to_tool_def_roundtrips_name_and_params():
    cal = next(t for t in DEFAULT_CATALOG if t.name == "calendar")
    td = cal.to_tool_def()
    assert td.name == "calendar"
    assert td.parameters == cal.params
