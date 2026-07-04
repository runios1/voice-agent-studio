/** Per-lead call detail for one campaign — the store-bound wrapper around the shared
 *  <CallDetailsTable/>. It folds each lead's event trail onto its snapshot
 *  (buildLeadRecords) over the UNION of the campaign's durable history (loaded on
 *  drill-in) and the live tail, so it reflects the whole campaign at any point — not
 *  just what streamed since the dashboard opened. Render-only: it summarizes stream +
 *  snapshot truth, it never computes control state (P2-7 boundary). */
import { useMemo } from "react";
import { useDashboardStore } from "./store";
import { buildLeadRecords } from "./metrics";
import type { Event } from "./types";
import { CallDetailsTable } from "./CallDetailsTable";

export function CampaignCallDetails() {
  const detail = useDashboardStore((s) => s.selectedCampaign);
  const id = useDashboardStore((s) => s.selectedCampaignId);
  const history = useDashboardStore((s) => s.campaignEvents);
  const historyLoading = useDashboardStore((s) => s.campaignEventsLoading);
  const liveEvents = useDashboardStore((s) => s.liveEvents);
  const openCall = useDashboardStore((s) => s.openCall);

  // Union of durable history + the live tail for this campaign, deduped by id, so a
  // freshly streamed event updates a row without waiting for a reload.
  const events = useMemo(() => {
    const merged = new Map<string, Event>();
    for (const e of history) merged.set(e.event_id, e);
    if (id) {
      for (const e of liveEvents) {
        if (e.campaign_id === id) merged.set(e.event_id, e);
      }
    }
    return [...merged.values()];
  }, [history, liveEvents, id]);

  const records = useMemo(
    () => buildLeadRecords(detail?.leads ?? [], events),
    [detail?.leads, events],
  );

  if (!detail || !id) {
    return <p className="p-6 text-sm text-muted">Loading campaign…</p>;
  }

  return (
    <CallDetailsTable
      records={records}
      onOpenCall={openCall}
      historyLoading={historyLoading}
      emptyText="No leads in this campaign."
    />
  );
}
