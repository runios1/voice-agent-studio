"""Dotted-path resolution + set-then-revalidate."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.config_gate.paths import (
    InvalidPath,
    apply_patch,
    get_at,
    path_exists,
    split_path,
)
from backend.config_gate.tests.conftest import USER
from backend.config_gate.service import AgentService
from backend.config_gate.repository import InMemoryConfigRepository


@pytest.fixture
def config():
    return AgentService(InMemoryConfigRepository()).create_agent(USER)


def test_get_at_reads_nested_leaf(config):
    assert get_at(config, "conversation.disclosure.must_disclose_ai") is True
    assert get_at(config, "guardrails.calling_hours.start_hour_local") == 8


def test_get_at_reads_subtree(config):
    hours = get_at(config, "guardrails.calling_hours")
    assert hours == {"start_hour_local": 8, "end_hour_local": 20}


@pytest.mark.parametrize("bad", ["", "conversation..tone", "nope", "conversation.persona.__class__"])
def test_split_and_get_reject_bad_paths(config, bad):
    assert not path_exists(config, bad)


def test_split_path_rejects_empty_segments():
    with pytest.raises(InvalidPath):
        split_path("a..b")


def test_apply_patch_sets_open_leaf(config):
    updated = apply_patch(config, "conversation.persona.tone", "warm")
    assert updated.conversation.persona.tone == "warm"
    # original is untouched (pure)
    assert config.conversation.persona.tone is None


def test_apply_patch_type_mismatch_raises_validation(config):
    with pytest.raises(ValidationError):
        apply_patch(config, "automation.calendar.meeting_length_minutes", "not-an-int")


def test_apply_patch_unknown_path_raises_invalidpath(config):
    with pytest.raises(InvalidPath):
        apply_patch(config, "conversation.persona.does_not_exist", "x")


def test_apply_patch_cannot_traverse_through_leaf(config):
    with pytest.raises(InvalidPath):
        apply_patch(config, "conversation.opening.deeper", "x")
