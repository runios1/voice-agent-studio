import { useEffect, useState } from "react";
import { fetchCurrentUser } from "../auth/authApi";
import { DashboardApp } from "./DashboardApp";
import type { DashboardApi } from "./dashboardApi";
import type { ConnectionsApi } from "../connections/connectionsApi";

/** Auth gate for the operations dashboard (served at its own /dashboard.html entry).
 * The studio's `Root` guards index.html; this does the same for the dashboard so a
 * signed-out visitor who lands here directly is sent to the login page rather than
 * shown the fleet. Mock mode has no backend session to check, so it renders straight
 * through — same posture as `main.tsx` in the studio. */
export function DashboardRoot({
  api,
  connectionsApi,
}: {
  api: DashboardApi;
  connectionsApi: ConnectionsApi;
}) {
  const [status, setStatus] = useState<"loading" | "ready">("loading");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const user = await fetchCurrentUser().catch(() => null);
      if (cancelled) return;
      if (!user) {
        // The login page is the studio entry (index.html); it renders LoginScreen
        // when signed out. A real navigation, not an in-app swap — separate entry.
        window.location.href = "/";
        return;
      }
      setStatus("ready");
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (status === "loading") {
    return <div className="flex h-full items-center justify-center text-muted">Loading…</div>;
  }
  return <DashboardApp api={api} connectionsApi={connectionsApi} />;
}
