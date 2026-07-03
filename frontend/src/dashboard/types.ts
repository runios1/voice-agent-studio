/**
 * TypeScript mirror of the FROZEN Phase-2 contracts the dashboard consumes.
 *
 *   - contracts/events/schema.py     -> Event, EventType, Severity
 *   - contracts/campaign/model.py    -> Campaign, Lead, CampaignState, LeadState
 *
 * READ-ONLY reflection of the backend contract (same discipline as
 * src/types/contracts.ts). The dashboard must not invent fields the contracts do
 * not define; if a shape here is wrong, file docs/contract-change-requests/p2-ws7.md
 * rather than diverging silently.
 */

// --------------------------------------------------------------------------- //
// events/schema.py
// --------------------------------------------------------------------------- //
export type EventType =
  // call lifecycle
  | "call.started"
  | "call.ended"
  | "disclosure.spoken" // compliance-critical
  | "call.escalated" // warm transfer to human
  // outcomes / actions
  | "slot.booked"
  | "tool.invoked"
  | "lead.outcome"
  | "followup.scheduled"
  // safety / control
  | "guardrail.tripped" // feeds auto-pause (P2-6)
  | "campaign.started"
  | "campaign.paused" // manual pause / global stop
  | "campaign.autopaused" // tripped by P2-6
  | "campaign.resumed";

export type Severity = "info" | "warning" | "critical";

/** The append-only envelope. `payload` carries event-type-specific fields (generic
 * on the wire; the dashboard only renders what a given type is known to carry). */
export interface Event {
  event_id: string;
  type: EventType;
  occurred_at: string; // ISO-8601
  severity: Severity;

  // correlation — tenant is ALWAYS present; the rest when scoped to them.
  tenant_id: string;
  campaign_id?: string | null;
  lead_id?: string | null;
  call_id?: string | null;
  agent_id?: string | null;

  payload: Record<string, unknown>;
}

// --------------------------------------------------------------------------- //
// campaign/model.py
// --------------------------------------------------------------------------- //
export type CampaignState = "draft" | "running" | "paused" | "completed";

export type LeadState =
  | "queued"
  | "dialing"
  | "in_call"
  | "outcome"
  | "follow_up"
  | "retry"
  | "done";

export interface GuardrailEnvelope {
  max_concurrent_calls: number;
  calls_per_minute: number;
  max_attempts_per_lead: number;
  calling_start_hour_local: number;
  calling_end_hour_local: number;
}

export interface Lead {
  id: string;
  campaign_id: string;
  tenant_id: string;
  phone: string;
  display_name?: string | null;
  state: LeadState;
  attempts: number;
  next_action_at?: string | null;
  outcome?: string | null;
  last_call_id?: string | null;
}

export interface Campaign {
  id: string;
  tenant_id: string;
  agent_id: string;
  name: string;
  state: CampaignState;
  envelope: GuardrailEnvelope;
  authorized_by?: string | null;
  authorized_at?: string | null;
  created_at: string;
  updated_at: string;
  // auto-pause bookkeeping (P2-6): why/when it self-paused, surfaced here.
  autopause_reason?: string | null;
}

/** A campaign plus its leads — the drill-down read, composed client-side from the
 *  two backend reads (GET /campaigns/{id} + GET /campaigns/{id}/leads). */
export interface CampaignDetail {
  campaign: Campaign;
  leads: Lead[];
}

// --------------------------------------------------------------------------- //
// Event backbone wire shape (events/router.py)
// --------------------------------------------------------------------------- //
/** How the event backbone wraps every event on the wire: the durable-log row is
 *  `{ seq, event }`, never a bare Event. `GET /events` returns `EventRow[]`; each
 *  `/events/stream` SSE frame carries one `EventRow` in its `data`. The frontend
 *  unwraps to `row.event` before handing `Event`s to the store/views. */
export interface EventRow {
  seq: number;
  event: Event;
}

// --------------------------------------------------------------------------- //
// Audit query filter (dashboard -> server; server stays authoritative)
// --------------------------------------------------------------------------- //
export interface AuditFilter {
  types?: EventType[];
  severity?: Severity;
  campaign_id?: string;
  /** ISO-8601 inclusive bounds. */
  since?: string;
  until?: string;
  limit?: number;
}

// --------------------------------------------------------------------------- //
// config_schema/schema.py AgentMeta (meta-only reflection, for the campaign
// builder's agent picker — GET /agents, api_contract.md)
// --------------------------------------------------------------------------- //
export type AgentStatus = "draft" | "ready";

export interface AgentSummary {
  id: string;
  name: string;
  status: AgentStatus;
}

// --------------------------------------------------------------------------- //
// Campaign creation (campaign builder -> POST /campaigns, control_api.py
// AuthorizeBody). Authorizing IS creating in this API — there is no separate
// draft step (P2-2).
// --------------------------------------------------------------------------- //
export interface NewLead {
  phone: string;
  display_name?: string;
}

export interface CreateCampaignInput {
  agent_id: string;
  name: string;
  leads: NewLead[];
  envelope?: GuardrailEnvelope;
}
