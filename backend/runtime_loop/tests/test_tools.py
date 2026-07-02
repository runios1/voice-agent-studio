"""In-call function layer tests (tools.py) — capability == exposed function."""

from __future__ import annotations

from backend.runtime_loop.fixtures import sample_ready_config
from backend.runtime_loop.tools import build_tools


def test_phase1_exposes_no_tools_by_default():
    config = sample_ready_config()
    config.automation.calendar.enabled = True
    config.automation.email.enabled = True
    assert build_tools(config) == []


def test_disabled_automation_yields_no_tool():
    config = sample_ready_config()  # both automations disabled
    assert build_tools(config, include_declared=True) == []


def test_enabled_calendar_exposes_only_book_meeting():
    config = sample_ready_config()
    config.automation.calendar.enabled = True
    tools = build_tools(config, include_declared=True)
    names = {t.name for t in tools}
    assert names == {"book_meeting"}
    (book,) = tools
    # Least privilege: model may only propose a time, not choose calendar/identity.
    assert set(book.parameters["properties"]) == {"start_iso"}
    assert book.parameters["additionalProperties"] is False


def test_enabled_email_constrains_to_approved_templates_no_free_urls():
    config = sample_ready_config()
    config.automation.email.enabled = True
    config.automation.email.template_ids = ["welcome-v1", "followup-v2"]
    tools = build_tools(config, include_declared=True)
    (email,) = [t for t in tools if t.name == "send_email"]
    props = email.parameters["properties"]
    # Only a template id, chosen from an enum — no body, no free-composed URL field.
    assert set(props) == {"template_id"}
    assert props["template_id"]["enum"] == ["welcome-v1", "followup-v2"]


def test_no_offer_discount_or_arbitrary_capability_exists():
    config = sample_ready_config()
    config.automation.calendar.enabled = True
    config.automation.email.enabled = True
    names = {t.name for t in build_tools(config, include_declared=True)}
    assert "offer_discount" not in names
    assert names <= {"book_meeting", "send_email"}
