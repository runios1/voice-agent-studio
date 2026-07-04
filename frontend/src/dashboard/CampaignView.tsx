/** Campaign altitude: one campaign's progress (lead-state tallies from the
 *  snapshot), its live calls (from the stream), recent outcomes, and its event
 *  trail. Live calls drill into the live-call view. Pause/resume here too. A local
 *  "Overview / Call details" toggle swaps the summary for the per-lead call table. */
import { useState } from "react";
import clsx from "clsx";
import { useDashboardStore } from "./store";
import {
  activeCalls,
  guardrailTrips,
  leadCounts,
  outcomeCounts,
  progress,
} from "./metrics";
import { EventFeed } from "./EventFeed";
import { CampaignCallDetails } from "./CampaignCallDetails";
import { CampaignStateBadge, ControlButton, ProgressBar } from "./ui";

type CampaignTab = "overview" | "details";

export function CampaignView() {
  const detail = useDashboardStore((s) => s.selectedCampaign);
  const id = useDashboardStore((s) => s.selectedCampaignId);
  const liveEvents = useDashboardStore((s) => s.liveEvents);
  const pending = useDashboardStore((s) => s.pending);
  const openCall = useDashboardStore((s) => s.openCall);
  const pause = useDashboardStore((s) => s.pauseCampaign);
  const resume = useDashboardStore((s) => s.resumeCampaign);
  const [tab, setTab] = useState<CampaignTab>("overview");

  if (!detail || !id) {
    return <p className="p-6 text-sm text-muted">Loading campaign…</p>;
  }
  const { campaign, leads } = detail;
  const counts = leadCounts(leads);
  const live = activeCalls(liveEvents, id);
  const outcomes = outcomeCounts(liveEvents, id);
  const trips = guardrailTrips(liveEvents, id);
  const busy = pending[`pause:${id}`] || pending[`resume:${id}`];
  const campaignEvents = liveEvents.filter((e) => e.campaign_id === id);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-line px-5 py-3">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-semibold">{campaign.name}</h2>
          <CampaignStateBadge state={campaign.state} />
          {trips > 0 && (
            <span className="text-xs text-amber-700" data-testid="trip-count">
              {trips} guardrail {trips === 1 ? "trip" : "trips"}
            </span>
          )}
        </div>
        {campaign.state === "running" ? (
          <ControlButton
            testid={`pause-${id}`}
            pending={busy}
            onClick={() => pause(id)}
          >
            Pause
          </ControlButton>
        ) : campaign.state === "paused" ? (
          <ControlButton
            testid={`resume-${id}`}
            pending={busy}
            onClick={() => resume(id)}
          >
            Resume
          </ControlButton>
        ) : null}
      </div>

      {campaign.autopause_reason && (
        <div
          data-testid="autopause-banner"
          className="border-b border-amber-200 bg-amber-50 px-5 py-2 text-sm text-amber-800"
        >
          Auto-paused: {campaign.autopause_reason}
        </div>
      )}

      <div className="flex gap-1 border-b border-line px-5 py-1.5">
        <SubTab active={tab === "overview"} onClick={() => setTab("overview")}>
          Overview
        </SubTab>
        <SubTab
          active={tab === "details"}
          onClick={() => setTab("details")}
          testid="tab-details"
        >
          Call details
        </SubTab>
      </div>

      {tab === "details" ? (
        <div className="min-h-0 flex-1">
          <CampaignCallDetails />
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col overflow-auto">
      <div className="grid gap-5 px-5 py-4 md:grid-cols-2">
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase text-muted">
            Progress
          </h3>
          <ProgressBar value={progress(leads)} />
          <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
            {(Object.keys(counts) as (keyof typeof counts)[]).map((k) => (
              <div key={k} className="rounded-md bg-panel px-2 py-1">
                <dt className="text-xs capitalize text-muted">
                  {k.replace("_", " ")}
                </dt>
                <dd className="tabular-nums">{counts[k]}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase text-muted">
            Outcomes (live)
          </h3>
          {Object.keys(outcomes).length === 0 ? (
            <p className="text-sm text-muted">No outcomes yet.</p>
          ) : (
            <dl className="grid grid-cols-2 gap-2 text-sm">
              {Object.entries(outcomes).map(([k, n]) => (
                <div key={k} className="rounded-md bg-panel px-2 py-1">
                  <dt className="text-xs capitalize text-muted">{k}</dt>
                  <dd className="tabular-nums">{n}</dd>
                </div>
              ))}
            </dl>
          )}
        </section>
      </div>

      <section className="px-5 pb-4">
        <h3 className="mb-2 text-xs font-semibold uppercase text-muted">
          Live calls
        </h3>
        {live.length === 0 ? (
          <p className="text-sm text-muted">No calls in progress.</p>
        ) : (
          <ul data-testid="live-calls" className="space-y-1">
            {live.map((e) => (
              <li key={e.call_id}>
                <button
                  data-testid={`open-call-${e.call_id}`}
                  className="flex w-full items-center gap-3 rounded-md border border-line px-3 py-2 text-left text-sm hover:bg-panel"
                  onClick={() => openCall(e.call_id!)}
                >
                  <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-500" />
                  <span className="font-mono text-xs">{e.call_id}</span>
                  <span className="text-muted">
                    {String(e.payload?.lead_name ?? e.lead_id ?? "")}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="min-h-0 flex-1 border-t border-line px-5 py-3">
        <h3 className="mb-2 text-xs font-semibold uppercase text-muted">
          Event trail
        </h3>
        <EventFeed events={campaignEvents} emptyText="No campaign events yet." />
      </section>
        </div>
      )}
    </div>
  );
}

function SubTab({
  active,
  onClick,
  children,
  testid,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  testid?: string;
}) {
  return (
    <button
      data-testid={testid}
      onClick={onClick}
      className={clsx(
        "rounded-md px-3 py-1 text-sm",
        active ? "bg-panel font-medium text-ink" : "text-muted hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}
