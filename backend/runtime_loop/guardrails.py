"""Hard-coded runtime guardrail steps.

These are the guardrails the design says must be enforced IN CODE, as hard runtime
steps — not as prompt text a malicious persona could talk the model out of
(D-security, this workstream's README).

Phase 1 covers the one guardrail that manifests in the text preview: AI disclosure.
Do-Not-Call / calling-hours / call-attempt caps are DIALER concerns (they gate
*whether a call happens*), and belong to the Phase-2 telephony + automation layer,
not to what the agent SAYS mid-conversation. The seam is here so they slot in.
"""

from __future__ import annotations

from contracts.config_schema.schema import AgentConfig

# Safe fallback used when disclosure is required but the platform/user left the
# script blank. Deliberately generic (no unfilled placeholders) so it is always a
# valid, standalone utterance.
DEFAULT_DISCLOSURE = (
    "Hi, before we go any further I want to let you know that I'm an AI assistant "
    "calling on behalf of the team."
)


def must_disclose(config: AgentConfig) -> bool:
    """Whether the AI-disclosure step must fire for this agent.

    True if EITHER the platform guardrail or the conversation-level flag requires it.
    (Both are LOCKED true by default in field_policy; we OR them so neither source
    can silently disable disclosure.)
    """
    return bool(
        config.guardrails.ai_disclosure_required
        or config.conversation.disclosure.must_disclose_ai
    )


def disclosure_line(config: AgentConfig) -> str:
    """The exact disclosure utterance to emit.

    Prefers the (user-tunable) `disclosure_script`; falls back to a safe default.
    This text is emitted by the engine as a guaranteed first agent turn — it does
    NOT come from the model, so no injected persona can suppress or reword it.
    """
    script = config.conversation.disclosure.disclosure_script
    if script and script.strip():
        return script.strip()
    return DEFAULT_DISCLOSURE
