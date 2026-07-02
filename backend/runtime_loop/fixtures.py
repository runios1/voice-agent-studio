"""Fixture AgentConfigs for tests and the demo surface.

These stand in for configs that WS2 (persistence) will produce at integration. Kept
here so tests and the demo share one honest, realistic SDR config.
"""

from __future__ import annotations

from datetime import datetime, timezone

from contracts.config_schema.schema import (
    AgentConfig,
    AgentMeta,
    AgentStatus,
    ComplianceGuardrails,
    ConversationConfig,
    Disclosure,
    Objection,
    Persona,
    Qualification,
    QualificationCriterion,
    VoicemailBehavior,
)


def sample_ready_config(
    *, owner_user_id: str = "user-1", agent_id: str = "agent-1"
) -> AgentConfig:
    """A realistic, deploy-ready SDR agent for Acme."""
    now = datetime(2026, 7, 2, tzinfo=timezone.utc)
    return AgentConfig(
        meta=AgentMeta(
            id=agent_id,
            owner_user_id=owner_user_id,
            name="Acme SDR",
            status=AgentStatus.READY,
            created_at=now,
            updated_at=now,
        ),
        guardrails=ComplianceGuardrails(
            allowed_link_domains=["acme.com", "calendly.com/acme"],
            forbidden_claims=[
                "guaranteed ROI",
                "we are the cheapest on the market",
            ],
        ),
        conversation=ConversationConfig(
            persona=Persona(
                display_name="Riley",
                role="an SDR for Acme, a workflow-automation platform",
                tone="warm, concise, and consultative",
                style_notes="Never talk over the prospect; ask one question at a time.",
            ),
            opening="Introduce yourself and Acme, and ask if it's a good time to talk.",
            voicemail=VoicemailBehavior(action="hang_up"),
            primary_objective="book a 15-minute discovery call",
            qualification=Qualification(
                framework="BANT",
                criteria=[
                    QualificationCriterion(
                        label="Budget",
                        question="Do you have budget allocated for tooling this quarter?",
                    ),
                    QualificationCriterion(
                        label="Team size",
                        question="How big is the ops team?",
                        disqualifying=True,
                    ),
                ],
            ),
            objections=[
                Objection(
                    trigger="We already use a competitor",
                    response_guidance="Acknowledge, ask what's working and what isn't, "
                    "position Acme's automation depth as the differentiator.",
                ),
            ],
            disclosure=Disclosure(
                disclosure_script=(
                    "Hi, quick heads-up before we start: I'm an AI assistant calling "
                    "on behalf of Acme."
                ),
            ),
        ),
        # Something we DON'T offer — must never surface in the runtime prompt.
        wishlist=["send the prospect an SMS", "integrate with Salesforce directly"],
    )
