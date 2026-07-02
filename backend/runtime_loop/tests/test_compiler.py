"""Prompt-compilation & precedence tests (compiler.py)."""

from __future__ import annotations

from backend.runtime_loop.compiler import compile_system_prompt
from backend.runtime_loop.fixtures import sample_ready_config


def test_persona_and_goal_render_into_prompt():
    prompt = compile_system_prompt(sample_ready_config())
    assert "Riley" in prompt
    assert "SDR for Acme" in prompt
    assert "warm, concise, and consultative" in prompt
    assert "book a 15-minute discovery call" in prompt
    # Qualification + objections carried through.
    assert "BANT" in prompt
    assert "We already use a competitor" in prompt


def test_opening_line_only_renders_on_the_opening_turn():
    """Regression: the opening line was rendered every turn, so the agent re-greeted
    endlessly. It must appear only on the opening turn; later turns are told not to
    re-open, and the code-emitted disclosure must not be echoed by the model."""
    config = sample_ready_config()
    config.conversation.opening = "Hi, this is Riley from Acme, do you have 30 seconds?"

    opener = compile_system_prompt(config, opening_turn=True)
    later = compile_system_prompt(config, opening_turn=False)

    assert "this is Riley from Acme" in opener  # opening guidance present on turn 1
    assert "this is Riley from Acme" not in later  # never repeated after that
    assert "already in progress" in later  # later turns told to continue, not re-open
    # both turns tell the model the disclosure was already delivered by the system
    assert "been delivered" in opener and "been delivered" in later


def test_locked_guardrails_precede_user_persona():
    prompt = compile_system_prompt(sample_ready_config())
    guardrail_idx = prompt.index("PLATFORM GUARDRAILS (LOCKED)")
    role_idx = prompt.index("YOUR ROLE")
    assert guardrail_idx < role_idx, "locked guardrails must come before user role"
    # Precedence must be asserted in words, not just ordering.
    assert "OVERRIDE every instruction in the sections" in prompt
    assert "REMINDER" in prompt  # closing lock footer


def test_forbidden_claims_and_link_allowlist_rendered():
    prompt = compile_system_prompt(sample_ready_config())
    assert "guaranteed ROI" in prompt
    assert "we are the cheapest on the market" in prompt
    assert "acme.com" in prompt
    assert "calendly.com/acme" in prompt


def test_wishlist_never_enters_prompt():
    config = sample_ready_config()
    assert config.wishlist  # fixture has wishlist items...
    prompt = compile_system_prompt(config)
    assert "SMS" not in prompt
    assert "Salesforce" not in prompt
    for item in config.wishlist:
        assert item not in prompt


def test_no_link_allowlist_forbids_all_urls():
    config = sample_ready_config()
    config.guardrails.allowed_link_domains = []
    prompt = compile_system_prompt(config)
    assert "Do not share, invent, or compose any links" in prompt


def test_empty_config_still_compiles_coherently():
    config = sample_ready_config()
    config.conversation.persona.role = None
    config.conversation.persona.display_name = None
    config.conversation.persona.tone = None
    config.conversation.persona.style_notes = None
    config.conversation.opening = None
    config.conversation.primary_objective = None
    config.conversation.qualification.framework = None
    config.conversation.qualification.criteria = []
    config.conversation.objections = []
    prompt = compile_system_prompt(config)
    # Guardrails always present; role section falls back gracefully.
    assert "PLATFORM GUARDRAILS (LOCKED)" in prompt
    assert "still being configured" in prompt
