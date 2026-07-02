/**
 * TypeScript mirror of the FROZEN contracts the frontend consumes.
 *
 *   - contracts/config_schema/schema.py        -> AgentConfig and its sub-models
 *   - contracts/config_schema/field_policy.py  -> FieldPolicy, Mutability, Layer
 *   - contracts/api/api_contract.md            -> the wire shapes below
 *
 * This is a READ-ONLY reflection of the backend contract. WS1 must not add fields
 * the schema does not define. If a shape here is wrong for our work, we file a
 * docs/contract-change-requests/ws1.md rather than diverging silently.
 */

// --------------------------------------------------------------------------- //
// field_policy.py
// --------------------------------------------------------------------------- //
export type Mutability = "locked" | "default" | "open";
export type Layer = "platform" | "user";

export interface FieldPolicy {
  path: string; // dotted path into AgentConfig, e.g. "conversation.persona.tone"
  owner_layer: Layer;
  mutability: Mutability;
  required_for_ready: boolean;
}

// --------------------------------------------------------------------------- //
// schema.py — AgentConfig
// --------------------------------------------------------------------------- //
export type AgentStatus = "draft" | "ready";

export interface AgentMeta {
  id: string;
  owner_user_id: string;
  name: string;
  status: AgentStatus;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface Persona {
  display_name?: string | null;
  role?: string | null;
  tone?: string | null;
  style_notes?: string | null;
}

export interface QualificationCriterion {
  label: string;
  question?: string | null;
  disqualifying: boolean;
}

export interface Qualification {
  framework?: string | null;
  criteria: QualificationCriterion[];
}

export interface Objection {
  trigger: string;
  response_guidance: string;
}

export interface Disclosure {
  must_disclose_ai: boolean;
  disclosure_script?: string | null;
}

export type VoicemailAction = "leave_message" | "hang_up";

export interface VoicemailBehavior {
  action: VoicemailAction | null; // null = undecided (a required gap the builder asks about)
  message?: string | null;
}

export interface ConversationConfig {
  persona: Persona;
  opening?: string | null;
  voicemail: VoicemailBehavior;
  primary_objective?: string | null;
  qualification: Qualification;
  objections: Objection[];
  disclosure: Disclosure;
  custom_instructions?: string | null;
}

export interface CalendarAutomation {
  enabled: boolean;
  calendar_ref?: string | null;
  meeting_length_minutes: number;
  booking_window_days: number;
}

export interface EmailAutomation {
  enabled: boolean;
  template_ids: string[];
}

export interface FollowUpStep {
  delay_hours: number;
  channel: "email";
  template_id: string;
}

export interface AutomationConfig {
  calendar: CalendarAutomation;
  email: EmailAutomation;
  follow_up: FollowUpStep[];
}

export interface CallingHours {
  start_hour_local: number;
  end_hour_local: number;
}

export interface ComplianceGuardrails {
  ai_disclosure_required: boolean;
  respect_do_not_call: boolean;
  calling_hours: CallingHours;
  allowed_link_domains: string[];
  max_call_attempts: number;
  forbidden_claims: string[];
}

export interface AgentConfig {
  meta: AgentMeta;
  guardrails: ComplianceGuardrails;
  conversation: ConversationConfig;
  automation: AutomationConfig;
  wishlist: string[];
}

// --------------------------------------------------------------------------- //
// api_contract.md — wire shapes
// --------------------------------------------------------------------------- //

/** GET /agents/{id} — config plus the resolved policy so the panel renders in one call. */
export interface AgentEnvelope {
  config: AgentConfig;
  policy: FieldPolicy[];
}

/** A single accepted config mutation. Emitted by builder SSE `patch` and returned by PATCH. */
export interface ConfigPatch {
  path: string;
  value: unknown;
}

/** Typed error shape shared by PATCH and (conversationally) builder `notice`. */
export type ErrorKind =
  | "locked_path"
  | "validation"
  | "screening_blocked"
  | "screening_flagged"
  | "rate_limited";

export interface ApiError {
  error: {
    kind: ErrorKind;
    path?: string;
    message: string;
  };
}

// --------------------------------------------------------------------------- //
// SSE event kinds (both builder and preview streams)
// --------------------------------------------------------------------------- //

/** builder: assistant reply text chunk | preview: agent reply text chunk */
export interface TokenEvent {
  event: "token";
  data: { text: string };
}

/** builder only: an accepted config mutation -> materialize a panel field */
export interface PatchEvent {
  event: "patch";
  data: ConfigPatch;
}

/** builder only: a rejected mutation, explained conversationally */
export interface NoticeEvent {
  event: "notice";
  data: { kind?: ErrorKind; path?: string; message: string };
}

/** stream terminator (optional; the stream closing also ends the turn) */
export interface DoneEvent {
  event: "done";
  data?: unknown;
}

export type BuilderStreamEvent =
  | TokenEvent
  | PatchEvent
  | NoticeEvent
  | DoneEvent;
export type PreviewStreamEvent = TokenEvent | DoneEvent;
