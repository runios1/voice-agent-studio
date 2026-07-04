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

export type DashboardView =
  | "fleet"
  | "campaign"
  | "live-call"
  | "audit"
  | "new-campaign"
  | "connections";

/** Initial view, honoring a `#connections` deep-link so the builder's "Connect …"
 *  CTAs (for a capability whose provider isn't connected yet) land straight on the
 *  Connections screen instead of the fleet. Any other hash falls back to "fleet". */
function initialView(): DashboardView {
  if (typeof window !== "undefined" && window.location.hash === "#connections") {
    return "connections";
  }
  return "fleet";
}

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
  /** The selected campaign's durable event history (from the audit log), loaded on
   *  drill-in so the call-detail view reflects the WHOLE campaign — not just what
   *  streamed into the bounded live tail since the dashboard opened. Live events for
   *  this campaign are merged on top of it in the view. */
  campaignEvents: Event[];
  campaignEventsLoading: boolean;

  auditFilter: AuditFilter;
  auditResults: Event[];
  auditLoading: boolean;

  /** in-flight control actions, keyed e.g. `pause:<id>`, `emergency-stop`. */
  pending: Record<string, boolean>;
  controlError: string | null;

  /** whether live-call escalation is wired in this build (false in real v1 mode,
   *  where there is no escalate route — the control is disabled). Set from the api
   *  at init; defaults true so mock/dev keep it enabled. */
  escalateAvailable: boolean;

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
  openNewCampaign: () => void;
  openConnections: () => void;

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

    view: initialView(),
    selectedCampaignId: null,
    selectedCallId: null,
    selectedCampaign: null,
    campaignEvents: [],
    campaignEventsLoading: false,

    auditFilter: { limit: 200 },
    auditResults: [],
    auditLoading: false,

    pending: {},
    controlError: null,
    escalateAvailable: true,

    init: (api) => set({ api, escalateAvailable: api.escalateAvailable !== false }),

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

    openNewCampaign: () =>
      set({ view: "new-campaign", selectedCampaignId: null, selectedCallId: null }),

    openConnections: () =>
      set({ view: "connections", selectedCampaignId: null, selectedCallId: null }),

    openCampaign: async (id) => {
      const api = get().api;
      // Clear the previous campaign's history so the detail view never shows stale
      // rows from another campaign while this one loads.
      set({
        view: "campaign",
        selectedCampaignId: id,
        selectedCallId: null,
        campaignEvents: [],
        campaignEventsLoading: true,
      });
      if (!api) {
        set({ campaignEventsLoading: false });
        return;
      }
      // Detail (campaign + leads) and the durable event history load in parallel; a
      // failure of either is non-fatal to the other.
      const detailP = api
        .getCampaign(id)
        .then((detail) => set({ selectedCampaign: detail }))
        .catch(() => set({ loadError: "Couldn't load that campaign." }));
      const historyP = api
        .queryAudit({ campaign_id: id, limit: 1000 })
        .then((campaignEvents) => {
          // Guard against a slow response for a campaign the user already left.
          if (get().selectedCampaignId === id) set({ campaignEvents });
        })
        .catch(() => {
          /* history is best-effort; the live tail still feeds the view */
        });
      await Promise.allSettled([detailP, historyP]);
      if (get().selectedCampaignId === id) set({ campaignEventsLoading: false });
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
