"""The completeness model: gaps computed deterministically from config + policy."""

from __future__ import annotations

from contracts.config_schema.schema import AgentStatus, QualificationCriterion

from backend.builder_loop.completeness import (
    REQUIRED_PATHS,
    evaluate_status,
    remaining_gaps,
)


def test_required_paths_come_from_policy():
    # The five truly-empty required fields on a fresh agent. voicemail.action is
    # required too but carries a sensible platform default ("hang_up"), so it is
    # already satisfied and not a gap.
    assert set(REQUIRED_PATHS) == {
        "conversation.persona.role",
        "conversation.persona.tone",
        "conversation.opening",
        "conversation.voicemail.action",
        "conversation.primary_objective",
        "conversation.qualification.criteria",
    }


def test_fresh_config_has_the_expected_gaps(fresh_config):
    gaps = remaining_gaps(fresh_config)
    assert "conversation.voicemail.action" not in gaps  # default satisfies it
    assert set(gaps) == {
        "conversation.persona.role",
        "conversation.persona.tone",
        "conversation.opening",
        "conversation.primary_objective",
        "conversation.qualification.criteria",
    }
    assert evaluate_status(fresh_config) is AgentStatus.DRAFT


def test_status_flips_ready_when_all_filled(fresh_config):
    c = fresh_config
    c.conversation.persona.role = "SDR for Acme"
    c.conversation.persona.tone = "warm and consultative"
    c.conversation.opening = "Hi, this is Ada from Acme — quick question about your rollout."
    c.conversation.primary_objective = "book a 15-minute discovery call"
    c.conversation.qualification.criteria.append(QualificationCriterion(label="budget"))
    assert remaining_gaps(c) == []
    assert evaluate_status(c) is AgentStatus.READY


def test_whitespace_only_string_is_still_a_gap(fresh_config):
    fresh_config.conversation.persona.role = "   "
    assert "conversation.persona.role" in remaining_gaps(fresh_config)
