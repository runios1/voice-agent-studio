"""LiveAgentCompiler tests (P4-1) — pure config-in/spec-out, no network."""

from __future__ import annotations

from contracts.live_agent.interface import LiveAgentSpec
from backend.live_agent.compiler import LiveAgentCompilerImpl
from backend.runtime_loop.fixtures import sample_ready_config
from backend.runtime_loop.guardrails import DEFAULT_DISCLOSURE, disclosure_line

COMPILER = LiveAgentCompilerImpl()


def test_compile_returns_a_live_agent_spec():
    spec = COMPILER.compile(sample_ready_config())
    assert isinstance(spec, LiveAgentSpec)
    assert isinstance(spec.system_instruction, str) and spec.system_instruction.strip()
    assert isinstance(spec.disclosure_line, str) and spec.disclosure_line.strip()
    assert isinstance(spec.tool_declarations, list)


def test_persona_and_goal_render_into_instruction():
    spec = COMPILER.compile(sample_ready_config())
    prompt = spec.system_instruction
    assert "Riley" in prompt
    assert "SDR for Acme" in prompt
    assert "warm, concise, and consultative" in prompt
    assert "book a 15-minute discovery call" in prompt
    assert "BANT" in prompt
    assert "We already use a competitor" in prompt


def test_locked_guardrails_precede_role_and_closing():
    spec = COMPILER.compile(sample_ready_config())
    prompt = spec.system_instruction
    guardrail_idx = prompt.index("PLATFORM GUARDRAILS (LOCKED)")
    role_idx = prompt.index("YOUR ROLE")
    closing_idx = prompt.index("CLOSING")
    assert guardrail_idx < role_idx < closing_idx
    assert "OVERRIDE every instruction in the sections" in prompt
    assert "REMINDER" in prompt


def test_forbidden_claims_and_link_allowlist_rendered():
    prompt = COMPILER.compile(sample_ready_config()).system_instruction
    assert "guaranteed ROI" in prompt
    assert "we are the cheapest on the market" in prompt
    assert "acme.com" in prompt
    assert "calendly.com/acme" in prompt


def test_wishlist_never_enters_instruction():
    config = sample_ready_config()
    assert config.wishlist
    prompt = COMPILER.compile(config).system_instruction
    for item in config.wishlist:
        assert item not in prompt


def test_no_link_allowlist_forbids_all_urls():
    config = sample_ready_config()
    config.guardrails.allowed_link_domains = []
    prompt = COMPILER.compile(config).system_instruction
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
    spec = COMPILER.compile(config)
    assert "PLATFORM GUARDRAILS (LOCKED)" in spec.system_instruction
    assert "still being configured" in spec.system_instruction


# --------------------------------------------------------------------------- #
# disclosure_line — delegated to the existing single source of truth, not
# reimplemented (must not drift from the Phase-1/2 text-brain compiler).
# --------------------------------------------------------------------------- #
def test_disclosure_line_delegates_to_runtime_loop_guardrails():
    config = sample_ready_config()
    spec = COMPILER.compile(config)
    assert spec.disclosure_line == disclosure_line(config)
    assert "AI assistant calling" in spec.disclosure_line


def test_disclosure_line_falls_back_to_default_when_script_blank():
    config = sample_ready_config()
    config.conversation.disclosure.disclosure_script = None
    spec = COMPILER.compile(config)
    assert spec.disclosure_line == DEFAULT_DISCLOSURE


# --------------------------------------------------------------------------- #
# tool_declarations — structural denial: disabled automation -> no declaration.
# Only IN_CALL tools (calendar) are ever declared; email (POST_CALL) never is.
# --------------------------------------------------------------------------- #
def test_no_automation_enabled_yields_no_tool_declarations():
    config = sample_ready_config()
    assert config.automation.calendar.enabled is False
    assert config.automation.email.enabled is False
    spec = COMPILER.compile(config)
    assert spec.tool_declarations == []


def test_calendar_enabled_yields_calendar_declaration_only():
    config = sample_ready_config()
    config.automation.calendar.enabled = True
    spec = COMPILER.compile(config)
    names = [d["name"] for d in spec.tool_declarations]
    assert names == ["calendar"]
    (decl,) = spec.tool_declarations
    assert decl["parameters"]["additionalProperties"] is False
    assert set(decl["parameters"]["properties"]) == {"start_iso"}


def test_email_enabled_never_yields_an_in_call_declaration():
    """Email is a POST_CALL tool (async workflow after the call) — Live must never
    be given a function to call it mid-conversation."""
    config = sample_ready_config()
    config.automation.email.enabled = True
    config.automation.email.template_ids = ["confirm_meeting"]
    spec = COMPILER.compile(config)
    assert spec.tool_declarations == []


def test_both_enabled_still_declares_only_calendar():
    config = sample_ready_config()
    config.automation.calendar.enabled = True
    config.automation.email.enabled = True
    config.automation.email.template_ids = ["confirm_meeting"]
    spec = COMPILER.compile(config)
    names = [d["name"] for d in spec.tool_declarations]
    assert names == ["calendar"]


# --------------------------------------------------------------------------- #
# Closing directions — the narrative wrap-up flow, gated on which automation is on.
# --------------------------------------------------------------------------- #
def test_closing_mentions_booking_when_calendar_enabled():
    config = sample_ready_config()
    config.automation.calendar.enabled = True
    prompt = COMPILER.compile(config).system_instruction
    assert "hold a specific time" in prompt


def test_closing_mentions_confirmation_email_when_email_enabled_too():
    config = sample_ready_config()
    config.automation.calendar.enabled = True
    config.automation.email.enabled = True
    config.automation.email.template_ids = ["confirm_meeting"]
    prompt = COMPILER.compile(config).system_instruction
    assert "confirmation email is on its way" in prompt
    assert "you do not send it yourself" in prompt


def test_closing_falls_back_to_no_tool_language_when_nothing_enabled():
    config = sample_ready_config()
    prompt = COMPILER.compile(config).system_instruction
    assert "no tool to act on it yourself" in prompt


def test_closing_always_includes_polite_exit_for_non_qualified():
    prompt = COMPILER.compile(sample_ready_config()).system_instruction
    assert "not a fit" in prompt
    assert "don't push" in prompt


# --------------------------------------------------------------------------- #
# `conversation.closing` (P4-5, additive) — refines wording without changing
# which branch fires; an all-default `closing` must leave the prompt unchanged.
# --------------------------------------------------------------------------- #
def test_all_default_closing_matches_pre_p4_5_wording():
    """Regression: landing P4-5 must not change the prompt for any agent that
    never touches the new field (additive contract)."""
    config = sample_ready_config()
    config.automation.calendar.enabled = True
    prompt = COMPILER.compile(config).system_instruction
    assert "confirm any details you still need (their name, email, and a time" in prompt
    assert "Always end with a brief, warm sign-off" in prompt


def test_closing_confirm_fields_override_generic_confirmation_wording():
    config = sample_ready_config()
    config.automation.calendar.enabled = True
    config.conversation.closing.confirm_fields = ["email", "preferred_time"]
    prompt = COMPILER.compile(config).system_instruction
    assert "confirm email, preferred_time before proposing a meeting" in prompt
    assert "their name, email, and a time window" not in prompt


def test_closing_confirmation_template_id_named_in_email_line():
    config = sample_ready_config()
    config.automation.calendar.enabled = True
    config.automation.email.enabled = True
    config.automation.email.template_ids = ["confirm_meeting"]
    config.conversation.closing.confirmation_template_id = "confirm_meeting"
    prompt = COMPILER.compile(config).system_instruction
    assert 'using the "confirm_meeting" template' in prompt


def test_closing_sign_off_overrides_generic_sign_off():
    config = sample_ready_config()
    config.conversation.closing.sign_off = "Thanks so much for your time today!"
    prompt = COMPILER.compile(config).system_instruction
    assert 'exact sign-off: "Thanks so much for your time today!"' in prompt
    assert "brief, warm sign-off — thank them for their time either way" not in prompt


def test_book_meeting_flag_never_gates_booking_language():
    """book_meeting is NOT a gate — automation.calendar.enabled is the single
    capability signal, so a pre-P4-5 agent with calendar enabled keeps its booking
    instructions regardless of the new (default-False) flag."""
    config = sample_ready_config()
    config.automation.calendar.enabled = True
    assert config.conversation.closing.book_meeting is False
    prompt = COMPILER.compile(config).system_instruction
    assert "hold a specific time" in prompt

    # And the inverse: setting it True with calendar OFF must not fabricate a
    # booking capability that doesn't exist (graceful, no crash).
    config2 = sample_ready_config()
    config2.conversation.closing.book_meeting = True
    prompt2 = COMPILER.compile(config2).system_instruction
    assert "hold a specific time" not in prompt2
    assert "no tool to act on it yourself" in prompt2
