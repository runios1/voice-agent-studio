import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { App } from "./components/App";
import { Root } from "./components/Root";
import { createHttpAgentApi, type AgentApi } from "./api/agentApi";
import { createMockAgentApi } from "./dev/mockApi";

/**
 * Phase 1 wiring: default to the mock API so the UI runs standalone before the
 * backend (workstreams 2–6) is merged. Set VITE_USE_MOCK=false (with the FastAPI
 * dev server up) to talk to the real seam via the /api proxy. Flipping this flag
 * is the ONLY change needed at integration — no component touches transport.
 *
 * Real accounts only apply to the non-mock path: the mock API has no backend
 * session to check, so it renders `App` directly against a fixed agent id, same
 * as before. The real path defers to `Root`, which checks the session, resolves
 * (or creates) the signed-in user's agent, and shows the login screen otherwise.
 */
const useMock = import.meta.env.VITE_USE_MOCK !== "false";

const root = createRoot(document.getElementById("root")!);

if (useMock) {
  const agentId = import.meta.env.VITE_AGENT_ID ?? "agent-demo";
  const api: AgentApi = createMockAgentApi(agentId);
  root.render(
    <StrictMode>
      <App api={api} agentId={agentId} />
    </StrictMode>,
  );
} else {
  const api: AgentApi = createHttpAgentApi();
  root.render(
    <StrictMode>
      <Root api={api} />
    </StrictMode>,
  );
}
