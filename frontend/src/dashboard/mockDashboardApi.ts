/**
 * A mock DashboardApi for `npm run dev` before P2-2/P2-3/P2-5 are merged. It holds a
 * few campaigns, an in-memory append-only event log, and a scripted "live" scenario
 * that emits events on a timer. Crucially, the control methods (pause/resume/stop/
 * escalate) EMIT the corresponding `campaign.*` / `call.escalated` event back onto
 * the same stream — so the UI reflects the new state FROM THE STREAM, exactly as it
 * will against the real orchestrator + P2-5 (server-authoritative, P2-7 boundary).
 *
 * DEV SCAFFOLDING, not a contract — the real backend replaces it wholesale. Tests use
 * their own fine-grained doubles (see src/dashboard/testMocks.ts).
 */
import type { DashboardApi } from "./dashboardApi";
import type {
  AgentSummary,
  AuditFilter,
  Campaign,
  CampaignDetail,
  CreateCampaignInput,
  Event,
  EventType,
  Lead,
  Severity,
} from "./types";

const NOW = () => new Date().toISOString();
let seq = 0;
const eid = () => `ev-${++seq}`;

function makeCampaign(id: string, name: string, state: Campaign["state"]): Campaign {
  return {
    id,
    tenant_id: "tenant-demo",
    agent_id: "agent-demo",
    name,
    state,
    envelope: {
      max_concurrent_calls: 5,
      calls_per_minute: 10,
      max_attempts_per_lead: 3,
      calling_start_hour_local: 8,
      calling_end_hour_local: 20,
    },
    authorized_by: "you@example.com",
    authorized_at: NOW(),
    created_at: NOW(),
    updated_at: NOW(),
    autopause_reason: null,
  };
}

function makeLeads(campaignId: string, n: number): Lead[] {
  const states: Lead["state"][] = [
    "done",
    "done",
    "in_call",
    "queued",
    "queued",
    "retry",
    "follow_up",
  ];
  return Array.from({ length: n }, (_, i) => ({
    id: `${campaignId}-lead-${i}`,
    campaign_id: campaignId,
    tenant_id: "tenant-demo",
    phone: `+1555000${String(1000 + i)}`,
    display_name: `Lead ${i}`,
    state: states[i % states.length],
    attempts: (i % 3),
    next_action_at: null,
    outcome: i % 5 === 0 ? "qualified" : null,
    last_call_id: null,
  }));
}

export function createMockDashboardApi(): DashboardApi {
  const campaigns: Campaign[] = [
    makeCampaign("camp-1", "West-coast SaaS Q3", "running"),
    makeCampaign("camp-2", "Renewals nudge", "paused"),
    makeCampaign("camp-3", "Cold outbound — dental", "completed"),
  ];
  campaigns[1].autopause_reason = "3 guardrail trips in 5 min";
  const leads: Record<string, Lead[]> = {
    "camp-1": makeLeads("camp-1", 14),
    "camp-2": makeLeads("camp-2", 9),
    "camp-3": makeLeads("camp-3", 20),
  };

  const agents: AgentSummary[] = [
    { id: "agent-demo", name: "Acme SDR", status: "ready" },
    { id: "agent-draft", name: "Still-building SDR", status: "draft" },
  ];

  const auditLog: Event[] = [];
  const listeners = new Set<(e: Event) => void>();

  function emit(
    type: EventType,
    over: Partial<Event> & { payload?: Record<string, unknown> },
  ): Event {
    const ev: Event = {
      event_id: eid(),
      type,
      occurred_at: NOW(),
      severity: (over.severity ?? "info") as Severity,
      tenant_id: "tenant-demo",
      campaign_id: over.campaign_id ?? null,
      lead_id: over.lead_id ?? null,
      call_id: over.call_id ?? null,
      agent_id: "agent-demo",
      payload: over.payload ?? {},
    };
    auditLog.push(ev);
    for (const l of listeners) l(ev);
    return ev;
  }

  let scenarioStarted = false;
  function startScenario() {
    if (scenarioStarted) return;
    scenarioStarted = true;
    const cid = "camp-1";

    // A repeating tick that walks a rotating set of live-ish events, occasionally
    // tripping a guardrail (so the auto-pause pressure + trip count is visible) and
    // emitting a transcript utterance (so the live-call view shows something).
    let i = 0;
    setInterval(() => {
      const call_id = `call-${(i % 3) + 1}`;
      const lead_id = `${cid}-lead-${(i % 3) + 1}`;
      const slotStart = new Date(Date.now() + 2 * 86400000).toISOString();
      const kinds: Array<[EventType, Record<string, unknown>, Severity?]> = [
        ["call.started", { lead_name: `Lead ${(i % 3) + 1}`, to_number: `+1555000${1000 + (i % 3) + 1}` }],
        ["disclosure.spoken", { speaker: "agent", utterance: "Hi, I'm an AI assistant for Acme.", text: "Hi, I'm an AI assistant for Acme." }],
        ["tool.invoked", { tool_name: "check_availability" }],
        ["slot.booked", { slot_start: slotStart, calendar_id: "sales@acme.com", speaker: "lead", utterance: "Thursday works." }],
        ["tool.invoked", { tool_name: "email", params: { to: `lead${(i % 3) + 1}@example.com` }, result_status: "ok" }],
        ["lead.outcome", { outcome: i % 2 ? "qualified" : "not_qualified" }],
        ["call.ended", { ended_reason: i % 3 === 0 ? "no_answer" : "completed", duration_seconds: 92 }],
      ];
      if (i % 7 === 6) {
        emit("guardrail.tripped", {
          campaign_id: cid,
          call_id,
          severity: "warning",
          payload: { rule: "out_of_hours_slot" },
        });
      } else {
        const [type, payload, sev] = kinds[i % kinds.length];
        emit(type, { campaign_id: cid, call_id, lead_id, severity: sev, payload });
      }
      i++;
    }, 2500);
  }

  let campaignSeq = campaigns.length;

  return {
    listCampaigns: async () => campaigns.map((c) => ({ ...c })),

    listAgents: async () => agents.map((a) => ({ ...a })),

    createCampaign: async (input: CreateCampaignInput): Promise<Campaign> => {
      const id = `camp-${++campaignSeq}`;
      const campaign = makeCampaign(id, input.name, "running");
      campaign.agent_id = input.agent_id;
      if (input.envelope) campaign.envelope = input.envelope;
      campaigns.push(campaign);
      leads[id] = input.leads.map((l, i) => ({
        id: `${id}-lead-${i}`,
        campaign_id: id,
        tenant_id: "tenant-demo",
        phone: l.phone,
        display_name: l.display_name ?? null,
        state: "queued",
        attempts: 0,
        next_action_at: null,
        outcome: null,
        last_call_id: null,
      }));
      emit("campaign.started", { campaign_id: id });
      return { ...campaign };
    },

    getCampaign: async (id): Promise<CampaignDetail> => {
      const campaign = campaigns.find((c) => c.id === id);
      if (!campaign) throw new Error("no such campaign");
      return { campaign: { ...campaign }, leads: (leads[id] ?? []).map((l) => ({ ...l })) };
    },

    queryAudit: async (filter: AuditFilter) => {
      let out = auditLog.slice();
      if (filter.types?.length) out = out.filter((e) => filter.types!.includes(e.type));
      if (filter.severity) out = out.filter((e) => e.severity === filter.severity);
      if (filter.campaign_id)
        out = out.filter((e) => e.campaign_id === filter.campaign_id);
      out = out.slice(-(filter.limit ?? 200));
      return out.reverse();
    },

    async *subscribeEvents(_filter, signal) {
      startScenario();
      const queue: Event[] = [];
      let wake: (() => void) | null = null;
      const push = (e: Event) => {
        queue.push(e);
        wake?.();
        wake = null;
      };
      listeners.add(push);
      try {
        while (!signal?.aborted) {
          if (queue.length) {
            yield queue.shift()!;
            continue;
          }
          await new Promise<void>((r) => {
            wake = r;
            signal?.addEventListener("abort", () => r(), { once: true });
          });
        }
      } finally {
        listeners.delete(push);
      }
    },

    pauseCampaign: async (id) => {
      const c = campaigns.find((x) => x.id === id);
      if (c) c.state = "paused";
      emit("campaign.paused", { campaign_id: id, payload: { by: "you@example.com" } });
    },
    resumeCampaign: async (id) => {
      const c = campaigns.find((x) => x.id === id);
      if (c) {
        c.state = "running";
        c.autopause_reason = null;
      }
      emit("campaign.resumed", { campaign_id: id });
    },
    emergencyStopAll: async () => {
      for (const c of campaigns) {
        if (c.state === "running") {
          c.state = "paused";
          emit("campaign.paused", {
            campaign_id: c.id,
            severity: "critical",
            payload: { reason: "global emergency stop" },
          });
        }
      }
    },
    escalateCall: async (callId) => {
      emit("call.escalated", {
        campaign_id: "camp-1",
        call_id: callId,
        severity: "warning",
        payload: { to: "human" },
      });
    },
  };
}
