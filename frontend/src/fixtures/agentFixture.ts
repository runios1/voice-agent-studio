/**
 * Fixtures used by tests and by `npm run dev` before the backend is merged.
 * FIELD_POLICY mirrors contracts/config_schema/field_policy.py exactly; the seeded
 * config mirrors what `POST /agents` returns (platform layer populated, user fields
 * empty). If these drift from the frozen contract, that's a bug in this file.
 */
import type { AgentConfig, FieldPolicy } from "../types/contracts";

export const FIELD_POLICY: FieldPolicy[] = [
  // platform guardrails
  { path: "guardrails.ai_disclosure_required", owner_layer: "platform", mutability: "locked", required_for_ready: false },
  { path: "guardrails.respect_do_not_call", owner_layer: "platform", mutability: "locked", required_for_ready: false },
  { path: "guardrails.calling_hours", owner_layer: "platform", mutability: "locked", required_for_ready: false },
  { path: "guardrails.allowed_link_domains", owner_layer: "platform", mutability: "locked", required_for_ready: false },
  { path: "guardrails.forbidden_claims", owner_layer: "platform", mutability: "locked", required_for_ready: false },
  { path: "guardrails.max_call_attempts", owner_layer: "platform", mutability: "default", required_for_ready: false },
  { path: "conversation.disclosure.must_disclose_ai", owner_layer: "platform", mutability: "locked", required_for_ready: false },
  // platform defaults the user may tune
  { path: "conversation.disclosure.disclosure_script", owner_layer: "platform", mutability: "default", required_for_ready: false },
  { path: "conversation.qualification.framework", owner_layer: "platform", mutability: "default", required_for_ready: false },
  // user-owned details; the completeness model
  { path: "conversation.persona.role", owner_layer: "user", mutability: "open", required_for_ready: true },
  { path: "conversation.persona.tone", owner_layer: "user", mutability: "open", required_for_ready: true },
  { path: "conversation.opening", owner_layer: "user", mutability: "open", required_for_ready: true },
  { path: "conversation.voicemail.action", owner_layer: "user", mutability: "open", required_for_ready: true },
  { path: "conversation.primary_objective", owner_layer: "user", mutability: "default", required_for_ready: true },
  { path: "conversation.qualification.criteria", owner_layer: "user", mutability: "open", required_for_ready: true },
  { path: "conversation.objections", owner_layer: "user", mutability: "open", required_for_ready: false },
  { path: "conversation.custom_instructions", owner_layer: "user", mutability: "open", required_for_ready: false },
  { path: "automation.calendar", owner_layer: "user", mutability: "open", required_for_ready: false },
  { path: "automation.email", owner_layer: "user", mutability: "open", required_for_ready: false },
];

export function makeSeededDraft(id = "agent-demo"): AgentConfig {
  const now = new Date("2026-07-02T12:00:00Z").toISOString();
  return {
    meta: {
      id,
      owner_user_id: "user-demo",
      name: "Untitled agent",
      status: "draft",
      version: 1,
      created_at: now,
      updated_at: now,
    },
    guardrails: {
      ai_disclosure_required: true,
      respect_do_not_call: true,
      calling_hours: { start_hour_local: 8, end_hour_local: 20 },
      allowed_link_domains: ["acme.com", "calendly.com"],
      max_call_attempts: 3,
      forbidden_claims: ["guaranteed pricing", "medical advice"],
    },
    conversation: {
      persona: { display_name: null, role: null, tone: null, style_notes: null },
      opening: null,
      voicemail: { action: null, message: null },
      primary_objective: null,
      qualification: { framework: "BANT", criteria: [] },
      objections: [],
      disclosure: {
        must_disclose_ai: true,
        disclosure_script: "Hi, I'm an AI assistant calling on behalf of Acme.",
      },
      custom_instructions: null,
    },
    automation: {
      calendar: {
        enabled: false,
        calendar_ref: null,
        meeting_length_minutes: 30,
        booking_window_days: 14,
      },
      email: { enabled: false, template_ids: [] },
      follow_up: [],
    },
    wishlist: [],
  };
}
