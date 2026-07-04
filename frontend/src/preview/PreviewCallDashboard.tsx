/** "In your dashboard" — a live mirror of how THIS preview call would appear in the ops
 *  Call-details view. It folds the structured events the server forwards for the call
 *  (via the `event` wire frame) through the SAME `buildLeadRecords` + `<CallDetailsTable/>`
 *  the real dashboard uses, so the preview shows the identical row filling in — dialed →
 *  answered → meeting booked → email sent → qualified — as the call progresses.
 *
 *  Self-contained: it's a synthetic single "lead" for this one call and writes to nothing.
 *  Preview events carry no lead_id (campaign_id is "preview"), so we attribute them via a
 *  synthetic lead whose `last_call_id` is the call's id — exactly how the dashboard
 *  correlates call-scoped events to a lead. */
import { useMemo } from "react";
import type { Event, Lead, LeadState } from "../dashboard/types";
import { buildLeadRecords } from "../dashboard/metrics";
import { CallDetailsTable } from "../dashboard/CallDetailsTable";

const PREVIEW_LEAD_ID = "preview-call";

export function PreviewCallDashboard({ events }: { events: Event[] }) {
  const records = useMemo(() => {
    const callId = events.find((e) => e.call_id)?.call_id ?? null;
    const started = events.some((e) => e.type === "call.started");
    const ended = events.some((e) => e.type === "call.ended");
    // Track the lead's snapshot state from the call's own lifecycle so the State badge
    // moves alongside the event-derived cells (queued → in call → done).
    const state: LeadState = ended ? "done" : started ? "in_call" : "queued";
    const lead: Lead = {
      id: PREVIEW_LEAD_ID,
      campaign_id: "preview",
      tenant_id: "preview",
      phone: "",
      display_name: "Live preview call",
      state,
      attempts: started ? 1 : 0,
      last_call_id: callId,
      outcome: null, // let the lead.outcome event decide (qualified / not_qualified / …)
    };
    return buildLeadRecords([lead], events);
  }, [events]);

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="preview-dashboard">
      <div className="border-b border-line px-4 py-2 text-xs font-semibold uppercase text-muted">
        In your dashboard
      </div>
      <div className="min-h-0 flex-1">
        <CallDetailsTable
          records={records}
          showSummary={false}
          showFilters={false}
          defaultExpandedId={PREVIEW_LEAD_ID}
          emptyText="Start the call to see it appear here."
        />
      </div>
    </div>
  );
}
