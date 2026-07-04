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
import { CampaignBuilder } from "./CampaignBuilder";
import { LiveCallView } from "./LiveCallView";
import { AuditView } from "./AuditView";
import { ConnectionsView } from "../connections/ConnectionsView";
import type { ConnectionsApi } from "../connections/connectionsApi";
import { Logomark } from "../components/Brand";
import { ThemeToggle } from "../components/ThemeToggle";

export function DashboardApp({
  api,
  connectionsApi,
}: {
  api: DashboardApi;
  connectionsApi: ConnectionsApi;
}) {
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
  const openConnections = useDashboardStore((s) => s.openConnections);

  useEffect(() => {
    init(api);
    void loadFleet();
    startStream();
    return () => stopStream();
  }, [api, init, loadFleet, startStream, stopStream]);

  const onFleetSide =
    view === "fleet" || view === "campaign" || view === "live-call" || view === "new-campaign";

  return (
    <div className="flex h-full flex-col">
      <header className="glass sticky top-0 z-10 flex items-center gap-4 border-b border-line/70 px-4 py-2.5">
        <span className="flex items-center gap-2.5">
          <Logomark className="h-8 w-8" />
          <span className="font-display text-[15px] font-semibold tracking-tight text-ink">
            Operations
          </span>
        </span>
        <nav className="ml-2 flex gap-1 rounded-full border border-line/70 bg-panel/60 p-1">
          <TabButton active={onFleetSide} onClick={openFleet}>
            Fleet
          </TabButton>
          <TabButton active={view === "connections"} onClick={openConnections}>
            Connections
          </TabButton>
          <TabButton active={view === "audit"} onClick={openAudit}>
            Audit
          </TabButton>
        </nav>

        <div className="ml-auto flex items-center gap-3">
          <span
            data-testid="connection"
            className="flex items-center gap-1.5 text-xs text-muted"
          >
            <span
              className={clsx(
                "h-2 w-2 rounded-full",
                connected ? "bg-signal animate-pulse-ring" : "bg-muted/50",
              )}
            />
            {connected ? "live" : "offline"}
          </span>
          {/* Link back to the builder studio (separate entry/root). */}
          <a
            href="/"
            className="rounded-full px-3 py-1.5 text-sm text-muted transition-colors hover:bg-panel hover:text-ink"
          >
            ← Agent studio
          </a>
          <ThemeToggle />
        </div>
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
        <div
          className="border-b border-red-500/20 bg-red-500/10 px-4 py-2 text-sm text-red-600 dark:text-red-300"
          role="alert"
        >
          {controlError ?? loadError}
        </div>
      )}

      <main className="min-h-0 flex-1 bg-canvas">
        {view === "fleet" && <FleetView />}
        {view === "new-campaign" && <CampaignBuilder />}
        {view === "campaign" && <CampaignView />}
        {view === "live-call" && <LiveCallView />}
        {view === "audit" && <AuditView />}
        {view === "connections" && <ConnectionsView api={connectionsApi} />}
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
        "rounded-full px-4 py-1 text-sm transition-all",
        active
          ? "bg-surface font-semibold text-ink shadow-card"
          : "text-muted hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}
