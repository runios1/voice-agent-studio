/** The dashboard shell. Two top tabs — Fleet and Audit — and a drill-down from
 *  Fleet → Campaign → Live-call via breadcrumb. Boots the fleet snapshot and opens
 *  the live event subscription; every view renders off the one store.
 *
 *  Self-contained: this area does NOT touch the Phase-1 builder/preview app. The
 *  integrator mounts it into the real nav (see DONE.md); until then `main.tsx` here
 *  runs it standalone. */
import { useEffect } from "react";
import clsx from "clsx";
import type { DashboardApi } from "./dashboardApi";
import { useDashboardStore } from "./store";
import { FleetView } from "./FleetView";
import { CampaignView } from "./CampaignView";
import { LiveCallView } from "./LiveCallView";
import { AuditView } from "./AuditView";

export function DashboardApp({ api }: { api: DashboardApi }) {
  const init = useDashboardStore((s) => s.init);
  const loadFleet = useDashboardStore((s) => s.loadFleet);
  const startStream = useDashboardStore((s) => s.startStream);
  const stopStream = useDashboardStore((s) => s.stopStream);

  const view = useDashboardStore((s) => s.view);
  const connected = useDashboardStore((s) => s.connected);
  const loadError = useDashboardStore((s) => s.loadError);
  const controlError = useDashboardStore((s) => s.controlError);
  const selectedCampaign = useDashboardStore((s) => s.selectedCampaign);
  const selectedCallId = useDashboardStore((s) => s.selectedCallId);
  const openFleet = useDashboardStore((s) => s.openFleet);
  const openCampaign = useDashboardStore((s) => s.openCampaign);
  const openAudit = useDashboardStore((s) => s.openAudit);

  useEffect(() => {
    init(api);
    void loadFleet();
    startStream();
    return () => stopStream();
  }, [api, init, loadFleet, startStream, stopStream]);

  const onFleetSide = view !== "audit";

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-4 border-b border-line px-4 py-2">
        <span className="text-sm font-semibold">Operations dashboard</span>
        <nav className="flex gap-1">
          <TabButton active={onFleetSide} onClick={openFleet}>
            Fleet
          </TabButton>
          <TabButton active={view === "audit"} onClick={openAudit}>
            Audit
          </TabButton>
        </nav>
        <span
          data-testid="connection"
          className="ml-auto flex items-center gap-1.5 text-xs text-muted"
        >
          <span
            className={clsx(
              "h-2 w-2 rounded-full",
              connected ? "bg-emerald-500" : "bg-slate-300",
            )}
          />
          {connected ? "live" : "offline"}
        </span>
      </header>

      {onFleetSide && (view === "campaign" || view === "live-call") && (
        <div className="flex items-center gap-1 border-b border-line px-4 py-1 text-xs text-muted">
          <button className="hover:text-ink" onClick={openFleet}>
            Fleet
          </button>
          {selectedCampaign && (
            <>
              <span>/</span>
              <button
                className="hover:text-ink"
                onClick={() => openCampaign(selectedCampaign.campaign.id)}
              >
                {selectedCampaign.campaign.name}
              </button>
            </>
          )}
          {view === "live-call" && selectedCallId && (
            <>
              <span>/</span>
              <span className="font-mono text-ink">{selectedCallId}</span>
            </>
          )}
        </div>
      )}

      {(loadError || controlError) && (
        <div className="bg-red-50 px-4 py-2 text-sm text-red-700" role="alert">
          {controlError ?? loadError}
        </div>
      )}

      <main className="min-h-0 flex-1">
        {view === "fleet" && <FleetView />}
        {view === "campaign" && <CampaignView />}
        {view === "live-call" && <LiveCallView />}
        {view === "audit" && <AuditView />}
      </main>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
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
