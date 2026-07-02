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
 * ⚠ The control endpoints below are P2-2's and are NOT yet in the frozen
 * contracts/api. Paths here are the dashboard's assumed shape; the integrator must
 * reconcile them with P2-2's real routes (see DONE.md). Everything is mocked until
 * then.
 */
import type { AuditFilter, Campaign, CampaignDetail, Event } from "./types";
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
  /** POST /control/emergency-stop — global stop across every campaign. */
  emergencyStopAll(): Promise<void>;
  /** POST /calls/{id}/escalate — warm-transfer a live call to a human (P2-D6). */
  escalateCall(callId: string): Promise<void>;
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

  return {
    listCampaigns: () => getJson<Campaign[]>("/campaigns"),

    getCampaign: (id) =>
      getJson<CampaignDetail>(`/campaigns/${encodeURIComponent(id)}`),

    queryAudit: (filter) => getJson<Event[]>(`/events?${filterToQuery(filter)}`),

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
    emergencyStopAll: () => post("/control/emergency-stop"),
    escalateCall: (callId) => post(`/calls/${encodeURIComponent(callId)}/escalate`),
  };
}

/** The stream server may wrap events as `event: <type>\ndata: <Event JSON>`, or send
 *  a bare JSON `Event`. Accept both; a record must carry a parsed Event object. */
export function rawToEvent(raw: RawSseEvent): Event | null {
  const d = raw.data;
  if (d && typeof d === "object" && "event_id" in d && "type" in d) {
    return d as Event;
  }
  return null;
}

export function filterToQuery(filter: AuditFilter): string {
  const q = new URLSearchParams();
  if (filter.types?.length) q.set("types", filter.types.join(","));
  if (filter.severity) q.set("severity", filter.severity);
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
