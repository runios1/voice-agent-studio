/**
 * Test doubles for DashboardApi. A controllable fake whose event subscription is
 * driven event-by-event from the test (so we can assert LIVE updates), and whose
 * control methods record calls and optionally emit a reflecting event back onto the
 * stream (mirroring the real server-authoritative flow: click → server → event →
 * UI). Tests import this, not mockDashboardApi.ts (that's dev scaffolding).
 */
import type { DashboardApi } from "./dashboardApi";
import type {
  AgentSummary,
  Campaign,
  CampaignDetail,
  CreateCampaignInput,
  Event,
  Lead,
} from "./types";
import { useDashboardStore } from "./store";

/** A push-driven async channel of events for subscribeEvents. */
export function makeEventChannel() {
  const queue: Event[] = [];
  let resolveNext: (() => void) | null = null;
  let closed = false;
  const push = (e: Event) => {
    queue.push(e);
    resolveNext?.();
    resolveNext = null;
  };
  const close = () => {
    closed = true;
    resolveNext?.();
    resolveNext = null;
  };
  async function* stream(signal?: AbortSignal): AsyncGenerator<Event> {
    while (!closed && !signal?.aborted) {
      if (queue.length) {
        yield queue.shift()!;
        continue;
      }
      await new Promise<void>((r) => {
        resolveNext = r;
        signal?.addEventListener("abort", () => r(), { once: true });
      });
    }
    while (queue.length) yield queue.shift()!;
  }
  return { push, close, stream };
}

export interface Calls {
  pause: string[];
  resume: string[];
  emergencyStop: number;
  escalate: string[];
  audit: number;
  createCampaign: CreateCampaignInput[];
}

interface Opts {
  campaigns?: Campaign[];
  leads?: Record<string, Lead[]>;
  auditResults?: Event[];
  channel?: ReturnType<typeof makeEventChannel>;
  /** if true, control calls push a reflecting event onto the channel. */
  reflect?: boolean;
  agents?: AgentSummary[];
  /** override createCampaign's behavior, e.g. to simulate a server rejection. */
  createCampaign?: (input: CreateCampaignInput) => Promise<Campaign>;
}

export function makeAgentSummary(over: Partial<AgentSummary> = {}): AgentSummary {
  return { id: "agent-demo", name: "Acme SDR", status: "ready", ...over };
}

export function makeCampaign(over: Partial<Campaign> = {}): Campaign {
  return {
    id: "camp-1",
    tenant_id: "tenant-demo",
    agent_id: "agent-demo",
    name: "Test campaign",
    state: "running",
    envelope: {
      max_concurrent_calls: 5,
      calls_per_minute: 10,
      max_attempts_per_lead: 3,
      calling_start_hour_local: 8,
      calling_end_hour_local: 20,
    },
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    autopause_reason: null,
    ...over,
  };
}

export function makeLead(over: Partial<Lead> = {}): Lead {
  return {
    id: "camp-1-lead-0",
    campaign_id: "camp-1",
    tenant_id: "tenant-demo",
    phone: "+15550000000",
    state: "queued",
    attempts: 0,
    ...over,
  };
}

export function makeEvent(over: Partial<Event> = {}): Event {
  return {
    event_id: over.event_id ?? `ev-${Math.random().toString(36).slice(2)}`,
    type: over.type ?? "call.started",
    occurred_at: over.occurred_at ?? "2026-01-01T12:00:00Z",
    severity: over.severity ?? "info",
    tenant_id: "tenant-demo",
    campaign_id: over.campaign_id ?? null,
    lead_id: over.lead_id ?? null,
    call_id: over.call_id ?? null,
    agent_id: over.agent_id ?? null,
    payload: over.payload ?? {},
  };
}

export function fakeApi(opts: Opts = {}): { api: DashboardApi; calls: Calls; channel: ReturnType<typeof makeEventChannel> } {
  const channel = opts.channel ?? makeEventChannel();
  const campaigns = opts.campaigns ?? [makeCampaign()];
  const leads = opts.leads ?? {};
  const agents = opts.agents ?? [makeAgentSummary()];
  const calls: Calls = {
    pause: [],
    resume: [],
    emergencyStop: 0,
    escalate: [],
    audit: 0,
    createCampaign: [],
  };

  const api: DashboardApi = {
    listCampaigns: async () => campaigns.map((c) => ({ ...c })),
    listAgents: async () => agents.map((a) => ({ ...a })),
    createCampaign: async (input) => {
      calls.createCampaign.push(input);
      if (opts.createCampaign) return opts.createCampaign(input);
      const campaign = makeCampaign({
        id: `camp-${campaigns.length + 1}`,
        agent_id: input.agent_id,
        name: input.name,
        state: "running",
        ...(input.envelope ? { envelope: input.envelope } : {}),
      });
      campaigns.push(campaign);
      leads[campaign.id] = input.leads.map((l, i) =>
        makeLead({
          id: `${campaign.id}-lead-${i}`,
          campaign_id: campaign.id,
          phone: l.phone,
          display_name: l.display_name ?? null,
        }),
      );
      return { ...campaign };
    },
    getCampaign: async (id): Promise<CampaignDetail> => {
      const campaign = campaigns.find((c) => c.id === id) ?? makeCampaign({ id });
      return { campaign: { ...campaign }, leads: (leads[id] ?? []).map((l) => ({ ...l })) };
    },
    queryAudit: async () => {
      calls.audit++;
      return (opts.auditResults ?? []).map((e) => ({ ...e }));
    },
    subscribeEvents: (_filter, signal) => channel.stream(signal),
    pauseCampaign: async (id) => {
      calls.pause.push(id);
      if (opts.reflect) channel.push(makeEvent({ type: "campaign.paused", campaign_id: id }));
    },
    resumeCampaign: async (id) => {
      calls.resume.push(id);
      if (opts.reflect) channel.push(makeEvent({ type: "campaign.resumed", campaign_id: id }));
    },
    emergencyStopAll: async () => {
      calls.emergencyStop++;
      if (opts.reflect)
        for (const c of campaigns)
          channel.push(makeEvent({ type: "campaign.paused", campaign_id: c.id }));
    },
    escalateCall: async (callId) => {
      calls.escalate.push(callId);
      if (opts.reflect)
        channel.push(makeEvent({ type: "call.escalated", call_id: callId }));
    },
  };
  return { api, calls, channel };
}

/** Reset the singleton dashboard store to a clean slate between tests. */
export function resetStore() {
  useDashboardStore.getState().stopStream();
  useDashboardStore.setState({
    api: null,
    campaigns: [],
    liveEvents: [],
    connected: false,
    loadError: null,
    view: "fleet",
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
  });
}

/** Wire a fake api into the store, load the fleet, and open the live stream. */
export async function mountStore(opts: Opts = {}) {
  resetStore();
  const f = fakeApi(opts);
  useDashboardStore.getState().init(f.api);
  await useDashboardStore.getState().loadFleet();
  useDashboardStore.getState().startStream();
  return f;
}
