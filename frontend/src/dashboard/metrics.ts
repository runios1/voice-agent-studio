/**
 * Pure derivations over the event stream + campaign snapshots. Kept pure and
 * separate so the dashboard RENDERS stream/snapshot truth rather than inventing
 * business state (P2-7 boundary). Nothing here decides control outcomes — it only
 * summarizes what the stream already reported.
 */
import type { Campaign, Event, Lead, LeadState } from "./types";

/** Call ids currently in-flight: a `call.started` with no later `call.ended`.
 *  Returns the started events (newest first) so the UI can show who's live now. */
export function activeCalls(events: Event[], campaignId?: string): Event[] {
  const ended = new Set<string>();
  for (const e of events) {
    if (e.type === "call.ended" && e.call_id) ended.add(e.call_id);
  }
  const seen = new Set<string>();
  const live: Event[] = [];
  // walk newest-first so the first sighting of a call_id is its latest start
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.type !== "call.started" || !e.call_id) continue;
    if (campaignId && e.campaign_id !== campaignId) continue;
    if (seen.has(e.call_id) || ended.has(e.call_id)) continue;
    seen.add(e.call_id);
    live.push(e);
  }
  return live;
}

/** Every event for one call, oldest-first — the live-call view's trail. */
export function callTrail(events: Event[], callId: string): Event[] {
  return events.filter((e) => e.call_id === callId);
}

const LEAD_STATES: LeadState[] = [
  "queued",
  "dialing",
  "in_call",
  "outcome",
  "follow_up",
  "retry",
  "done",
];

/** Per-state lead tallies from the authoritative snapshot (not the stream). */
export function leadCounts(leads: Lead[]): Record<LeadState, number> {
  const out = Object.fromEntries(LEAD_STATES.map((s) => [s, 0])) as Record<
    LeadState,
    number
  >;
  for (const l of leads) out[l.state]++;
  return out;
}

/** Completion fraction 0..1: terminal (`done`) leads over total. */
export function progress(leads: Lead[]): number {
  if (leads.length === 0) return 0;
  const done = leads.filter((l) => l.state === "done").length;
  return done / leads.length;
}

/** Outcome tallies from `lead.outcome` events for a campaign (live view). */
export function outcomeCounts(
  events: Event[],
  campaignId: string,
): Record<string, number> {
  const out: Record<string, number> = {};
  for (const e of events) {
    if (e.type !== "lead.outcome" || e.campaign_id !== campaignId) continue;
    const outcome = String(e.payload?.outcome ?? "unknown");
    out[outcome] = (out[outcome] ?? 0) + 1;
  }
  return out;
}

/** Guardrail-trip count in the buffer for a campaign — the signal auto-pause acts
 *  on (P2-6); shown here so an operator sees WHY a campaign is near a stop. */
export function guardrailTrips(events: Event[], campaignId: string): number {
  return events.filter(
    (e) => e.type === "guardrail.tripped" && e.campaign_id === campaignId,
  ).length;
}

/** Apply a campaign lifecycle event onto the displayed campaign state/reason. The
 *  stream is the source of pause/auto-pause truth (P2-7: "show state from the
 *  stream"), so we reflect it rather than optimistically flipping on the click. */
export function applyLifecycle(campaign: Campaign, ev: Event): Campaign {
  switch (ev.type) {
    case "campaign.started":
    case "campaign.resumed":
      return { ...campaign, state: "running", autopause_reason: null };
    case "campaign.paused":
      return { ...campaign, state: "paused" };
    case "campaign.autopaused":
      return {
        ...campaign,
        state: "paused",
        autopause_reason: String(
          ev.payload?.reason ?? campaign.autopause_reason ?? "auto-paused",
        ),
      };
    default:
      return campaign;
  }
}

export const CAMPAIGN_LIFECYCLE_TYPES = new Set<Event["type"]>([
  "campaign.started",
  "campaign.paused",
  "campaign.autopaused",
  "campaign.resumed",
]);

// --------------------------------------------------------------------------- //
// Per-lead call detail — the "who was dialed / who answered / qualified? / booked?
// / emailed?" drill-down. Folds a lead's event trail onto its snapshot so an
// operator can see, per lead, exactly what happened and when. Pure: it summarizes
// the stream + snapshot, it never invents state (P2-7 boundary).
// --------------------------------------------------------------------------- //

/** How a dial resolved, derived from the last `call.ended` reason (or an in-flight
 *  call). `not_dialed` = never dialed yet. */
export type AnswerStatus =
  | "answered"
  | "no_answer"
  | "voicemail"
  | "in_progress"
  | "failed"
  | "not_dialed";

export interface Booking {
  start?: string; // ISO or free label of the booked slot
  end?: string;
  where?: string; // calendar id / location, when the event carries one
}

export interface EmailSent {
  at: string; // when the email tool ran
  to?: string; // recipient, when the payload carries one
  status?: string; // ok / error / denied
}

/** A single lead's full story, folded from its snapshot + event trail. */
export interface LeadRecord {
  lead: Lead;
  dialed: boolean;
  attempts: number;
  answer: AnswerStatus;
  endedReason: string | null;
  outcome: string | null; // raw outcome string (qualified / not_qualified / …)
  qualified: boolean | null; // true / false / null(=unknown)
  booking: Booking | null;
  email: EmailSent | null;
  disclosed: boolean;
  escalated: boolean;
  followups: number;
  guardrailTrips: number;
  toNumber: string | null;
  lastActivityAt: string | null;
  callId: string | null;
  events: Event[]; // this lead's events, oldest-first
}

/** Read the first present string value among candidate payload keys. */
function pickStr(p: Record<string, unknown>, ...keys: string[]): string | undefined {
  for (const k of keys) {
    const v = p[k];
    if (typeof v === "string" && v) return v;
    if (typeof v === "number") return String(v);
  }
  return undefined;
}

const ANSWERED_REASONS = new Set(["completed", "hangup", "answered"]);
const VOICEMAIL_REASONS = new Set(["voicemail"]);
const NO_ANSWER_REASONS = new Set(["no_answer", "busy", "rejected", "canceled"]);

function qualifiedFrom(outcome: string | null): boolean | null {
  // A booked meeting IS a qualified lead (the orchestrator records the terminal lead
  // outcome as "booked"; the lead.outcome EVENT says "qualified" — treat both as such).
  if (outcome === "qualified" || outcome === "booked") return true;
  if (outcome === "not_qualified" || outcome === "do_not_call" || outcome === "opted_out")
    return false;
  return null;
}

/** Map each call_id to the lead it belongs to, using (a) the lead snapshot's
 *  `last_call_id` and (b) any event that carries BOTH a call_id and a lead_id. This
 *  lets call-scoped events that omit `lead_id` still attach to the right lead. */
function callToLead(leads: Lead[], events: Event[]): Map<string, string> {
  const map = new Map<string, string>();
  for (const l of leads) if (l.last_call_id) map.set(l.last_call_id, l.id);
  for (const e of events) {
    if (e.call_id && e.lead_id && !map.has(e.call_id)) map.set(e.call_id, e.lead_id);
  }
  return map;
}

/** Build one `LeadRecord` per lead by folding the campaign's events onto each lead's
 *  snapshot. `events` should be the campaign-scoped trail (history + live tail). The
 *  snapshot wins for authoritative fields (state, attempts, outcome); the stream
 *  fills in the "what happened" detail (answered?, booked?, emailed?, when). */
export function buildLeadRecords(leads: Lead[], events: Event[]): LeadRecord[] {
  const byCall = callToLead(leads, events);
  const perLead = new Map<string, Event[]>();
  for (const l of leads) perLead.set(l.id, []);
  for (const e of events) {
    const leadId = e.lead_id ?? (e.call_id ? byCall.get(e.call_id) : undefined);
    if (leadId && perLead.has(leadId)) perLead.get(leadId)!.push(e);
  }

  return leads.map((lead) => {
    const evs = (perLead.get(lead.id) ?? [])
      .slice()
      .sort((a, b) => a.occurred_at.localeCompare(b.occurred_at));

    let answer: AnswerStatus = "not_dialed";
    let endedReason: string | null = null;
    let booking: Booking | null = null;
    let email: EmailSent | null = null;
    let disclosed = false;
    let escalated = false;
    let followups = 0;
    let guardrailTrips = 0;
    let toNumber: string | null = null;
    let outcomeEvent: string | null = null;
    let dialedFromEvents = false;

    for (const e of evs) {
      const p = e.payload ?? {};
      switch (e.type) {
        case "call.started":
          dialedFromEvents = true;
          answer = "in_progress";
          toNumber = pickStr(p, "to_number", "to") ?? toNumber;
          break;
        case "call.ended": {
          endedReason = pickStr(p, "ended_reason") ?? endedReason;
          if (endedReason && ANSWERED_REASONS.has(endedReason)) answer = "answered";
          else if (endedReason && VOICEMAIL_REASONS.has(endedReason)) answer = "voicemail";
          else if (endedReason && NO_ANSWER_REASONS.has(endedReason)) answer = "no_answer";
          else if (endedReason === "error") answer = "failed";
          else answer = "answered"; // ended with no explicit reason → the call connected
          break;
        }
        case "disclosure.spoken":
          disclosed = true;
          break;
        case "slot.booked":
          booking = {
            start: pickStr(p, "slot_start", "slot", "start_iso", "start"),
            end: pickStr(p, "slot_end"),
            where: pickStr(p, "calendar_id", "location"),
          };
          break;
        case "tool.invoked": {
          const tool = pickStr(p, "tool_name", "tool", "name") ?? "";
          if (/email/i.test(tool)) {
            const params = (p.params ?? {}) as Record<string, unknown>;
            email = {
              at: e.occurred_at,
              to: pickStr(p, "to") ?? pickStr(params, "to", "attendee_email", "recipient"),
              status: pickStr(p, "result_status"),
            };
          }
          break;
        }
        case "lead.outcome":
          outcomeEvent = pickStr(p, "outcome") ?? outcomeEvent;
          break;
        case "followup.scheduled":
          followups++;
          break;
        case "call.escalated":
          escalated = true;
          break;
        case "guardrail.tripped":
          guardrailTrips++;
          break;
      }
    }

    // Snapshot is authoritative for outcome; the stream fills in when it's absent.
    const outcome = lead.outcome ?? outcomeEvent;
    const dialed =
      dialedFromEvents ||
      lead.attempts > 0 ||
      !!lead.last_call_id ||
      (lead.state !== "queued" && lead.state !== "done") ||
      (lead.state === "done" && !!outcome);

    // If the lead is mid-call per the snapshot but we saw no ended event, reflect that.
    if (answer === "not_dialed" && (lead.state === "in_call" || lead.state === "dialing")) {
      answer = "in_progress";
    }

    return {
      lead,
      dialed,
      attempts: lead.attempts,
      answer,
      endedReason,
      outcome,
      qualified: qualifiedFrom(outcome),
      booking,
      email,
      disclosed,
      escalated,
      followups,
      guardrailTrips,
      toNumber: toNumber ?? lead.phone ?? null,
      lastActivityAt: evs.length ? evs[evs.length - 1].occurred_at : null,
      callId: lead.last_call_id ?? evs.find((e) => e.call_id)?.call_id ?? null,
      events: evs,
    };
  });
}
