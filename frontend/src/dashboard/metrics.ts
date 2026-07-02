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
