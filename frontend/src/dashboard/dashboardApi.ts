/**
 * The dashboard's single door to the backend. Two backends it binds to:
 *   - the EVENT STREAM (contracts/events, served by P2-5) — a snapshot query for
 *     the audit log + a live SSE subscription for the four views;
 *   - the ORCHESTRATOR CONTROL API (P2-2) — pause / resume / global emergency stop /
 *     escalate. The server is the authority; the UI only calls it and reflects state.
 *
 * Everything is behind this interface so it can be dependency-injected: the real
 * HTTP impl talks to FastAPI; tests and `npm run dev` (pre-integration) pass a mock
 * that replays fixtures. The dashboard owns NO control logic — it renders server
 * truth and issues control calls (D-security: the server gate is the boundary).
 *
 * The real HTTP impl binds to contracts/dashboard_http/README.md (the FROZEN v1
 * seam onto the already-merged orchestrator control API + event backbone). Notable
 * adaptations pinned there: campaign detail is TWO reads composed client-side;
 * events arrive WRAPPED as `{ seq, event }` rows and are unwrapped to `Event`;
 * emergency-stop is the tenant-global `POST /emergency-stop`; and escalate is
 * DEFERRED in v1 (no route) so the real impl reports it unavailable (§3).
 */
import type {
  AgentSummary,
  AuditFilter,
  Campaign,
  CampaignDetail,
  CreateCampaignInput,
  Event,
  EventRow,
  Lead,
} from "./types";
import { parseSseStream, type RawSseEvent } from "../api/sse";

export class ControlFailure extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ControlFailure";
    this.status = status;
  }
}

export interface DashboardApi {
  /** GET /campaigns — fleet snapshot (all campaigns for the authed tenant). */
  listCampaigns(): Promise<Campaign[]>;

  /** GET /campaigns/{id} — a campaign plus its per-lead states (drill-down). */
  getCampaign(id: string): Promise<CampaignDetail>;

  /** GET /agents — meta-only list, for the campaign builder's agent picker
   *  (api_contract.md; same door the Phase-1 studio uses). */
  listAgents(): Promise<AgentSummary[]>;

  /** POST /campaigns — authorize a new campaign (control_api.py). Authorizing
   *  IS creating: bounded autonomy means this immediately starts the dispatch
   *  loop, so the builder UI treats it as the deliberate, one-way step. */
  createCampaign(input: CreateCampaignInput): Promise<Campaign>;

  /** GET /events — a filtered slice of the immutable log (audit view). Filtering is
   *  server-side (authoritative); the client just passes the filter through. */
  queryAudit(filter: AuditFilter): Promise<Event[]>;

  /** GET /events/stream (SSE) — the live tail of the event stream. `filter` narrows
   *  the subscription (e.g. one campaign / one call) server-side. Yields one parsed
   *  `Event` per SSE record until `signal` aborts or the connection closes. */
  subscribeEvents(
    filter: AuditFilter,
    signal?: AbortSignal,
  ): AsyncGenerator<Event>;

  // --- control (P2-2 kill switch, P2-D3) -------------------------------------
  /** POST /campaigns/{id}/pause — stop new dials, let live calls finish. */
  pauseCampaign(id: string): Promise<void>;
  /** POST /campaigns/{id}/resume — resume a paused campaign. */
  resumeCampaign(id: string): Promise<void>;
  /** POST /emergency-stop — tenant-global stop across every running campaign. */
  emergencyStopAll(): Promise<void>;
  /** Warm-transfer a live call to a human (P2-D6). DEFERRED in v1: there is no HTTP
   *  route yet (contract §3), so the real impl surfaces `escalateAvailable=false`
   *  and this rejects rather than calling a non-existent route. */
  escalateCall(callId: string): Promise<void>;

  /** Whether live-call escalation is wired in this build. `false` (real HTTP, v1)
   *  tells the UI to disable/hide the control; `undefined`/`true` (mock/dev) leaves
   *  it enabled. Escalation is a voice-runtime action, not part of the v1 seam. */
  readonly escalateAvailable?: boolean;
}

// --------------------------------------------------------------------------- //
// Real HTTP implementation
// --------------------------------------------------------------------------- //
export function createHttpDashboardApi(baseUrl = "/api"): DashboardApi {
  async function getJson<T>(path: string): Promise<T> {
    const res = await fetch(`${baseUrl}${path}`, {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    });
    if (!res.ok) throw await toFailure(res);
    return (await res.json()) as T;
  }

  async function post(path: string): Promise<void> {
    const res = await fetch(`${baseUrl}${path}`, {
      method: "POST",
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    });
    if (!res.ok) throw await toFailure(res);
  }

  async function postJson<T>(path: string, body: unknown): Promise<T> {
    const res = await fetch(`${baseUrl}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(body),
    });
    if (!res.ok) throw await toFailure(res);
    return (await res.json()) as T;
  }

  return {
    listCampaigns: () => getJson<Campaign[]>("/campaigns"),

    listAgents: () => getJson<AgentSummary[]>("/agents"),

    createCampaign: (input) => postJson<Campaign>("/campaigns", input),

    // Campaign detail is TWO reads (contract §1): the campaign and its leads are
    // separate routes, composed into CampaignDetail here.
    async getCampaign(id): Promise<CampaignDetail> {
      const enc = encodeURIComponent(id);
      const [campaign, leads] = await Promise.all([
        getJson<Campaign>(`/campaigns/${enc}`),
        getJson<Lead[]>(`/campaigns/${enc}/leads`),
      ]);
      return { campaign, leads };
    },

    // GET /events returns WRAPPED rows (`{ seq, event }`); unwrap to Event[] (§2).
    async queryAudit(filter): Promise<Event[]> {
      const rows = await getJson<EventRow[]>(`/events?${filterToQuery(filter)}`);
      return rows.map((r) => r.event);
    },

    async *subscribeEvents(filter, signal) {
      const res = await fetch(`${baseUrl}/events/stream?${filterToQuery(filter)}`, {
        headers: { Accept: "text/event-stream" },
        credentials: "same-origin",
        signal,
      });
      if (!res.ok || !res.body) throw await toFailure(res);
      for await (const raw of parseSseStream(res.body, signal)) {
        const ev = rawToEvent(raw);
        if (ev) yield ev;
      }
    },

    pauseCampaign: (id) => post(`/campaigns/${encodeURIComponent(id)}/pause`),
    resumeCampaign: (id) => post(`/campaigns/${encodeURIComponent(id)}/resume`),
    // Tenant-global, NOT per-campaign and NOT /control/emergency-stop (§1).
    emergencyStopAll: () => post("/emergency-stop"),
    // Escalate is deferred in v1 (§3): no route exists. Reject without a fetch so
    // we never call a non-existent endpoint; the UI keeps the control disabled.
    escalateCall: async (_callId) => {
      throw new ControlFailure("Escalation isn't available in this build.", 501);
    },
    escalateAvailable: false,
  };
}

/** Unwrap an SSE frame into an `Event`. The event backbone wraps each frame's
 *  `data` as a durable-log row `{ seq, event }` (contract §2); read `data.event`.
 *  A bare `Event` in `data` is also tolerated (mock/legacy). Non-event frames
 *  (keep-alive, pings) yield null. */
export function rawToEvent(raw: RawSseEvent): Event | null {
  const d = raw.data;
  if (!d || typeof d !== "object") return null;
  const inner = "event" in d ? (d as { event?: unknown }).event : d;
  if (inner && typeof inner === "object" && "event_id" in inner && "type" in inner) {
    return inner as Event;
  }
  return null;
}

export function filterToQuery(filter: AuditFilter): string {
  const q = new URLSearchParams();
  // Repeatable params: one `type=`/`severity=` per value, NOT a comma-joined list (§2).
  for (const t of filter.types ?? []) q.append("type", t);
  if (filter.severity) q.append("severity", filter.severity);
  if (filter.campaign_id) q.set("campaign_id", filter.campaign_id);
  if (filter.since) q.set("since", filter.since);
  if (filter.until) q.set("until", filter.until);
  if (filter.limit != null) q.set("limit", String(filter.limit));
  return q.toString();
}

async function toFailure(res: Response): Promise<ControlFailure> {
  let message = `Request failed (${res.status}).`;
  try {
    const body = (await res.json()) as { error?: { message?: string } };
    if (body?.error?.message) message = body.error.message;
  } catch {
    /* keep the generic message */
  }
  return new ControlFailure(message, res.status);
}
