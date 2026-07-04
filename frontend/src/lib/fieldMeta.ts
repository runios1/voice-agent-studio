/**
 * Presentation metadata for schema paths: a human label and how the value renders
 * / edits. This is pure UX chrome over the frozen schema — it invents no fields.
 * Anything not listed here falls back to a read-only JSON summary, so the panel
 * degrades gracefully if the schema grows before this map does.
 */
import type { FieldPolicy, VoicemailAction } from "../types/contracts";

export type Editor =
  | { kind: "text" }
  | { kind: "textarea" }
  | { kind: "select"; options: { value: string; label: string }[] }
  // an on/off switch over a boolean sub-field of the path's object (default
  // `.enabled`) — used for capability blocks like calendar/email automation.
  | { kind: "toggle"; field?: string; hint?: string }
  | { kind: "readonly" }; // lists/objects: display-only in Phase 1 (edit via chat)

export interface FieldMeta {
  label: string;
  editor: Editor;
}

const VOICEMAIL_OPTIONS: { value: VoicemailAction; label: string }[] = [
  { value: "hang_up", label: "Hang up" },
  { value: "leave_message", label: "Leave a message" },
];

export const FIELD_META: Record<string, FieldMeta> = {
  // user-owned conversation fields
  "conversation.persona.role": { label: "Role", editor: { kind: "text" } },
  "conversation.persona.tone": { label: "Tone", editor: { kind: "text" } },
  "conversation.opening": { label: "Opening line", editor: { kind: "textarea" } },
  "conversation.voicemail.action": {
    label: "If nobody picks up",
    editor: { kind: "select", options: VOICEMAIL_OPTIONS },
  },
  "conversation.primary_objective": {
    label: "Primary objective",
    editor: { kind: "text" },
  },
  "conversation.qualification.framework": {
    label: "Qualification framework",
    editor: { kind: "text" },
  },
  "conversation.qualification.criteria": {
    label: "Qualification criteria",
    editor: { kind: "readonly" },
  },
  "conversation.objections": { label: "Objections", editor: { kind: "readonly" } },
  "conversation.custom_instructions": {
    label: "Custom instructions",
    editor: { kind: "textarea" },
  },
  "conversation.disclosure.disclosure_script": {
    label: "AI disclosure script",
    editor: { kind: "textarea" },
  },
  "automation.calendar": {
    label: "Calendar booking",
    editor: {
      kind: "toggle",
      hint: "Lets the agent check availability and hold meetings. Connect your Google Calendar under Connections for it to work on a live call.",
    },
  },
  "automation.email": {
    label: "Email follow-up",
    editor: {
      kind: "toggle",
      hint: "Lets the agent send an approved confirmation/follow-up email after a call.",
    },
  },

  // platform guardrails (read-only, shown in the locked section)
  "guardrails.ai_disclosure_required": {
    label: "AI disclosure required",
    editor: { kind: "readonly" },
  },
  "guardrails.respect_do_not_call": {
    label: "Respect Do-Not-Call",
    editor: { kind: "readonly" },
  },
  "guardrails.calling_hours": { label: "Calling hours (local)", editor: { kind: "readonly" } },
  "guardrails.allowed_link_domains": {
    label: "Allowed link domains",
    editor: { kind: "readonly" },
  },
  "guardrails.forbidden_claims": {
    label: "Forbidden claims",
    editor: { kind: "readonly" },
  },
  "guardrails.max_call_attempts": {
    label: "Max call attempts",
    editor: { kind: "text" },
  },
  "conversation.disclosure.must_disclose_ai": {
    label: "Must disclose it's an AI",
    editor: { kind: "readonly" },
  },
};

export function metaFor(path: string): FieldMeta {
  return FIELD_META[path] ?? { label: path, editor: { kind: "readonly" } };
}

export function policyByPath(policy: FieldPolicy[]): Record<string, FieldPolicy> {
  return Object.fromEntries(policy.map((p) => [p.path, p]));
}
