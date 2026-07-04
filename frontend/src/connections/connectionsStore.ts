/**
 * Tenant connection state for the BUILDER app. The Agent panel's capability
 * toggles (calendar / email) must reflect whether the backing provider is
 * actually connected — a capability the tenant can't fulfil should be gated, not
 * silently promised (mirrors the D13 "never configured to promise what it can't
 * deliver" rule; the server is still the real enforcement).
 *
 * Kept as its own tiny store, separate from the agent-config store, because
 * connections are a tenant concern, not part of the agent artifact. `main.tsx`
 * injects the right ConnectionsApi (mock in `npm run dev`, HTTP otherwise) the
 * same way it injects the AgentApi.
 */
import { create } from "zustand";
import type { ConnectionInfo, ConnectionsApi } from "./connectionsApi";

interface ConnectionsState {
  api: ConnectionsApi | null;
  byProvider: Record<string, ConnectionInfo>;
  /** false until the first list() resolves (or fails); lets the UI avoid flashing
   *  a "Connect" prompt before we actually know the state. */
  loaded: boolean;
  init: (api: ConnectionsApi) => void;
  refresh: () => Promise<void>;
}

export const useConnectionsStore = create<ConnectionsState>((set, get) => ({
  api: null,
  byProvider: {},
  loaded: false,

  init: (api) => {
    set({ api });
    void get().refresh();
  },

  refresh: async () => {
    const api = get().api;
    if (!api) return;
    try {
      const list = await api.list();
      set({
        byProvider: Object.fromEntries(list.map((c) => [c.provider, c])),
        loaded: true,
      });
    } catch {
      // Couldn't reach the connections seam — treat as "nothing connected" so the
      // UI errs toward directing the user to Connections rather than offering a
      // capability that won't work. The server enforces the real gate regardless.
      set({ byProvider: {}, loaded: true });
    }
  },
}));

/** Which provider each capability toggle depends on. Mirrors the tool registry's
 *  provider ids; a path absent here isn't connection-gated. */
export const CAPABILITY_PROVIDER: Record<string, string> = {
  "automation.calendar": "google_calendar",
  "automation.email": "gmail",
};
