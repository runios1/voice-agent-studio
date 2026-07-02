/**
 * The dashboard's single source of UI truth (one Zustand store), mirroring the
 * builder app's `agentStore` discipline. It holds:
 *   - the fleet snapshot (`campaigns`) + the selected campaign's leads,
 *   - a bounded live tail of the event stream (`liveEvents`),
 *   - navigation (which of the four altitudes is showing),
 *   - the audit query result, and control-action status.
 *
 * SERVER-AUTHORITATIVE, like the builder: the UI never flips campaign state on a
 * click. A control call (pause/stop) goes to the orchestrator; the resulting
 * `campaign.*` event arrives on the stream and THAT reflects the new state
 * (applyLifecycle). This is the P2-7 boundary — render stream truth, don't compute
 * control state client-side.
 */
import { create } from "zustand";
import type { DashboardApi } from "./dashboardApi";
import { ControlFailure } from "./dashboardApi";
import type {
  AuditFilter,
  Campaign,
  CampaignDetail,
  Event,
} from "./types";
import { applyLifecycle, CAMPAIGN_LIFECYCLE_TYPES } from "./metrics";

const MAX_LIVE_EVENTS = 1000;

export type DashboardView = "fleet" | "campaign" | "live-call" | "audit";

export interface DashboardState {
  api: DashboardApi | null;

  campaigns: Campaign[];
  liveEvents: Event[];
  connected: boolean;
  loadError: string | null;

  view: DashboardView;
  selectedCampaignId: string | null;
  selectedCallId: string | null;
  selectedCampaign: CampaignDetail | null;

  auditFilter: AuditFilter;
  auditResults: Event[];
  auditLoading: boolean;

  /** in-flight control actions, keyed e.g. `pause:<id>`, `emergency-stop`. */
  pending: Record<string, boolean>;
  controlError: string | null;

  // actions
  init: (api: DashboardApi) => void;
  loadFleet: () => Promise<void>;
  startStream: (filter?: AuditFilter) => void;
  stopStream: () => void;
  ingest: (ev: Event) => void;

  openFleet: () => void;
  openCampaign: (id: string) => Promise<void>;
  openCall: (callId: string) => void;
  openAudit: () => void;

  setAuditFilter: (filter: AuditFilter) => void;
  runAudit: () => Promise<void>;

  pauseCampaign: (id: string) => Promise<void>;
  resumeCampaign: (id: string) => Promise<void>;
  emergencyStopAll: () => Promise<void>;
  escalateCall: (callId: string) => Promise<void>;
}

// The live subscription is a side-effect held outside React state.
let streamAbort: AbortController | null = null;

export const useDashboardStore = create<DashboardState>((set, get) => {
  const setPending = (key: string, on: boolean) =>
    set((s) => {
      const pending = { ...s.pending };
      if (on) pending[key] = true;
      else delete pending[key];
      return { pending };
    });

  const runControl = async (key: string, fn: () => Promise<void>) => {
    if (get().pending[key]) return;
    setPending(key, true);
    set({ controlError: null });
    try {
      await fn();
    } catch (err) {
      set({
        controlError:
          err instanceof ControlFailure
            ? err.message
            : "That control didn't go through — try again.",
      });
    } finally {
      setPending(key, false);
    }
  };

  return {
    api: null,
    campaigns: [],
    liveEvents: [],
    connected: false,
    loadError: null,

    view: "fleet",
    selectedCampaignId: null,
    selectedCallId: null,
    selectedCampaign: null,

    auditFilter: { limit: 200 },
    auditResults: [],
    auditLoading: false,

    pending: {},
    controlError: null,

    init: (api) => set({ api }),

    loadFleet: async () => {
      const api = get().api;
      if (!api) throw new Error("dashboardStore.init(api) must be called first");
      try {
        const campaigns = await api.listCampaigns();
        set({ campaigns, loadError: null });
      } catch {
        set({ loadError: "Couldn't load campaigns. Is the backend running?" });
      }
    },

    startStream: (filter = {}) => {
      const api = get().api;
      if (!api) return;
      streamAbort?.abort();
      const ac = new AbortController();
      streamAbort = ac;
      set({ connected: true });
      (async () => {
        try {
          for await (const ev of api.subscribeEvents(filter, ac.signal)) {
            if (ac.signal.aborted) break;
            get().ingest(ev);
          }
        } catch {
          /* stream dropped; surfaced via `connected` */
        } finally {
          if (streamAbort === ac) {
            streamAbort = null;
            set({ connected: false });
          }
        }
      })();
    },

    stopStream: () => {
      streamAbort?.abort();
      streamAbort = null;
      set({ connected: false });
    },

    ingest: (ev) =>
      set((s) => {
        const liveEvents = [...s.liveEvents, ev];
        if (liveEvents.length > MAX_LIVE_EVENTS) {
          liveEvents.splice(0, liveEvents.length - MAX_LIVE_EVENTS);
        }
        // Reflect campaign lifecycle transitions from the stream onto snapshots.
        let campaigns = s.campaigns;
        let selectedCampaign = s.selectedCampaign;
        if (CAMPAIGN_LIFECYCLE_TYPES.has(ev.type) && ev.campaign_id) {
          campaigns = campaigns.map((c) =>
            c.id === ev.campaign_id ? applyLifecycle(c, ev) : c,
          );
          if (selectedCampaign?.campaign.id === ev.campaign_id) {
            selectedCampaign = {
              ...selectedCampaign,
              campaign: applyLifecycle(selectedCampaign.campaign, ev),
            };
          }
        }
        return { liveEvents, campaigns, selectedCampaign };
      }),

    openFleet: () =>
      set({ view: "fleet", selectedCampaignId: null, selectedCallId: null }),

    openCampaign: async (id) => {
      const api = get().api;
      set({ view: "campaign", selectedCampaignId: id, selectedCallId: null });
      if (!api) return;
      try {
        const detail = await api.getCampaign(id);
        set({ selectedCampaign: detail });
      } catch {
        set({ loadError: "Couldn't load that campaign." });
      }
    },

    openCall: (callId) => set({ view: "live-call", selectedCallId: callId }),

    openAudit: () => {
      set({ view: "audit" });
      void get().runAudit();
    },

    setAuditFilter: (filter) => set({ auditFilter: filter }),

    runAudit: async () => {
      const api = get().api;
      if (!api) return;
      set({ auditLoading: true });
      try {
        const auditResults = await api.queryAudit(get().auditFilter);
        set({ auditResults, auditLoading: false });
      } catch {
        set({ auditLoading: false, loadError: "Audit query failed." });
      }
    },

    pauseCampaign: (id) =>
      runControl(`pause:${id}`, () => get().api!.pauseCampaign(id)),
    resumeCampaign: (id) =>
      runControl(`resume:${id}`, () => get().api!.resumeCampaign(id)),
    emergencyStopAll: () =>
      runControl("emergency-stop", () => get().api!.emergencyStopAll()),
    escalateCall: (callId) =>
      runControl(`escalate:${callId}`, () => get().api!.escalateCall(callId)),
  };
});
