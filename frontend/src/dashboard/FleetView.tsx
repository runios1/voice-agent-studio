/** Fleet altitude: every campaign for the tenant, the GLOBAL emergency stop, and
 *  per-campaign pause/resume. Controls call the orchestrator; state shown here is
 *  reflected from the stream/snapshot (never flipped optimistically on click). */
import { useDashboardStore } from "./store";
import { activeCalls } from "./metrics";
import { CampaignStateBadge, ControlButton } from "./ui";

export function FleetView() {
  const campaigns = useDashboardStore((s) => s.campaigns);
  const liveEvents = useDashboardStore((s) => s.liveEvents);
  const pending = useDashboardStore((s) => s.pending);
  const openCampaign = useDashboardStore((s) => s.openCampaign);
  const openNewCampaign = useDashboardStore((s) => s.openNewCampaign);
  const pause = useDashboardStore((s) => s.pauseCampaign);
  const resume = useDashboardStore((s) => s.resumeCampaign);
  const emergencyStop = useDashboardStore((s) => s.emergencyStopAll);

  const anyRunning = campaigns.some((c) => c.state === "running");

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-line px-5 py-3">
        <h2 className="text-sm font-semibold">Fleet</h2>
        <div className="flex items-center gap-2">
          <ControlButton testid="new-campaign" onClick={openNewCampaign}>
            + New campaign
          </ControlButton>
          <ControlButton
            testid="emergency-stop"
            danger
            pending={pending["emergency-stop"]}
            disabled={!anyRunning}
            onClick={emergencyStop}
          >
            ⛔ Emergency stop all
          </ControlButton>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto px-5 py-3">
        {campaigns.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted">
            No campaigns yet.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs text-muted">
                <th className="py-2 font-medium">Campaign</th>
                <th className="py-2 font-medium">State</th>
                <th className="py-2 font-medium">Live calls</th>
                <th className="py-2 font-medium">Note</th>
                <th className="py-2" />
              </tr>
            </thead>
            <tbody>
              {campaigns.map((c) => {
                const live = activeCalls(liveEvents, c.id).length;
                const busy =
                  pending[`pause:${c.id}`] || pending[`resume:${c.id}`];
                return (
                  <tr
                    key={c.id}
                    data-testid={`fleet-row-${c.id}`}
                    className="border-b border-line/60 hover:bg-panel"
                  >
                    <td className="py-2">
                      <button
                        data-testid={`open-campaign-${c.id}`}
                        className="font-medium text-ink hover:text-accent"
                        onClick={() => openCampaign(c.id)}
                      >
                        {c.name}
                      </button>
                    </td>
                    <td className="py-2">
                      <CampaignStateBadge state={c.state} />
                    </td>
                    <td className="py-2 tabular-nums">{live}</td>
                    <td className="py-2 text-xs text-amber-600 dark:text-amber-300">
                      {c.autopause_reason ?? ""}
                    </td>
                    <td className="py-2 text-right">
                      {c.state === "running" ? (
                        <ControlButton
                          testid={`pause-${c.id}`}
                          pending={busy}
                          onClick={() => pause(c.id)}
                        >
                          Pause
                        </ControlButton>
                      ) : c.state === "paused" ? (
                        <ControlButton
                          testid={`resume-${c.id}`}
                          pending={busy}
                          onClick={() => resume(c.id)}
                        >
                          Resume
                        </ControlButton>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
