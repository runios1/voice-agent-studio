/**
 * Standalone dev entry for the operations dashboard (served at /dashboard.html by
 * Vite). Defaults to the mock backend so the four views run before P2-2/P2-3/P2-5
 * are merged; set VITE_USE_MOCK=false (with FastAPI up) to hit the real seam via the
 * /api proxy. At integration the dashboard is mounted into the real app nav — this
 * file is the pre-integration harness only (see DONE.md).
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../index.css";
import { DashboardApp } from "./DashboardApp";
import { createHttpDashboardApi, type DashboardApi } from "./dashboardApi";
import { createMockDashboardApi } from "./mockDashboardApi";

const useMock = import.meta.env.VITE_USE_MOCK !== "false";
const api: DashboardApi = useMock
  ? createMockDashboardApi()
  : createHttpDashboardApi();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <DashboardApp api={api} />
  </StrictMode>,
);
