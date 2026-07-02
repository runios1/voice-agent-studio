import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { App } from "./components/App";
import { createHttpAgentApi, type AgentApi } from "./api/agentApi";
import { createMockAgentApi } from "./dev/mockApi";

/**
 * Phase 1 wiring: default to the mock API so the UI runs standalone before the
 * backend (workstreams 2–6) is merged. Set VITE_USE_MOCK=false (with the FastAPI
 * dev server up) to talk to the real seam via the /api proxy. Flipping this flag
 * is the ONLY change needed at integration — no component touches transport.
 */
const useMock = import.meta.env.VITE_USE_MOCK !== "false";
const agentId = import.meta.env.VITE_AGENT_ID ?? "agent-demo";
const api: AgentApi = useMock ? createMockAgentApi(agentId) : createHttpAgentApi();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App api={api} agentId={agentId} />
  </StrictMode>,
);
