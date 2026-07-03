import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createHttpDashboardApi,
  ControlFailure,
  filterToQuery,
  rawToEvent,
} from "./dashboardApi";
import type { Campaign, Event, EventRow, Lead } from "./types";
import { makeCampaign, makeEvent, makeLead } from "./testMocks";

// --------------------------------------------------------------------------- //
// filterToQuery — repeatable `type`/`severity`, per contract §2
// --------------------------------------------------------------------------- //
describe("filterToQuery", () => {
  it("serializes types as REPEATED `type` params (not a comma-joined `types=`)", () => {
    const qs = filterToQuery({
      types: ["call.started", "call.ended"],
      severity: "warning",
      limit: 50,
    });
    const q = new URLSearchParams(qs);
    expect(q.getAll("type")).toEqual(["call.started", "call.ended"]);
    expect(q.get("types")).toBeNull();
    expect(q.getAll("severity")).toEqual(["warning"]);
    expect(q.get("limit")).toBe("50");
    expect(q.get("campaign_id")).toBeNull();
  });

  it("passes single-valued correlation/bounds through", () => {
    const q = new URLSearchParams(
      filterToQuery({ campaign_id: "camp-1", since: "2026-01-01T00:00:00Z" }),
    );
    expect(q.get("campaign_id")).toBe("camp-1");
    expect(q.get("since")).toBe("2026-01-01T00:00:00Z");
  });

  it("is empty for an empty filter", () => {
    expect(filterToQuery({})).toBe("");
  });
});

// --------------------------------------------------------------------------- //
// rawToEvent — unwrap the `{ seq, event }` row from the SSE frame's data (§2)
// --------------------------------------------------------------------------- //
describe("rawToEvent", () => {
  it("unwraps the Event from a `{ seq, event }` row", () => {
    const ev = makeEvent({ event_id: "x", type: "slot.booked" });
    const row: EventRow = { seq: 7, event: ev };
    expect(rawToEvent({ event: "event", data: row })?.event_id).toBe("x");
    expect(rawToEvent({ event: "event", data: row })?.type).toBe("slot.booked");
  });

  it("tolerates a bare Event in data (mock/legacy)", () => {
    const ev = makeEvent({ event_id: "y", type: "call.started" });
    expect(rawToEvent({ event: "message", data: ev })?.event_id).toBe("y");
  });

  it("rejects records that aren't events", () => {
    expect(rawToEvent({ event: "ping", data: "keep-alive" })).toBeNull();
    expect(rawToEvent({ event: "message", data: { foo: 1 } })).toBeNull();
    expect(rawToEvent({ event: "event", data: { seq: 1, event: { foo: 1 } } })).toBeNull();
  });
});

// --------------------------------------------------------------------------- //
// createHttpDashboardApi — the real wire shapes (contract §1–§3)
// --------------------------------------------------------------------------- //
type FetchStub = (url: string, init?: RequestInit) => Response | Promise<Response>;

function stubFetch(handler: FetchStub) {
  const spy = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
    handler(String(input), init),
  );
  vi.stubGlobal("fetch", spy);
  return spy;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("createHttpDashboardApi", () => {
  it("getCampaign composes CampaignDetail from TWO reads (§1)", async () => {
    const campaign: Campaign = makeCampaign({ id: "camp-1" });
    const leads: Lead[] = [makeLead({ id: "camp-1-lead-0" }), makeLead({ id: "camp-1-lead-1" })];
    const seen: string[] = [];
    stubFetch((url) => {
      seen.push(url);
      if (url.endsWith("/campaigns/camp-1")) return jsonResponse(campaign);
      if (url.endsWith("/campaigns/camp-1/leads")) return jsonResponse(leads);
      throw new Error(`unexpected url ${url}`);
    });

    const detail = await createHttpDashboardApi().getCampaign("camp-1");
    expect(detail.campaign.id).toBe("camp-1");
    expect(detail.leads.map((l) => l.id)).toEqual(["camp-1-lead-0", "camp-1-lead-1"]);
    expect(seen).toContain("/api/campaigns/camp-1");
    expect(seen).toContain("/api/campaigns/camp-1/leads");
  });

  it("queryAudit unwraps `{ seq, event }` rows to Event[] (§2)", async () => {
    const rows: EventRow[] = [
      { seq: 1, event: makeEvent({ event_id: "e1", type: "call.started" }) },
      { seq: 2, event: makeEvent({ event_id: "e2", type: "call.ended" }) },
    ];
    let calledUrl = "";
    stubFetch((url) => {
      calledUrl = url;
      return jsonResponse(rows);
    });

    const events: Event[] = await createHttpDashboardApi().queryAudit({
      types: ["call.started", "call.ended"],
    });
    expect(events.map((e) => e.event_id)).toEqual(["e1", "e2"]);
    expect(calledUrl).toContain("/api/events?");
    expect(new URLSearchParams(calledUrl.split("?")[1]).getAll("type")).toEqual([
      "call.started",
      "call.ended",
    ]);
  });

  it("emergencyStopAll POSTs the tenant-global /emergency-stop (§1)", async () => {
    let method = "";
    let path = "";
    const spy = stubFetch((url, init) => {
      method = init?.method ?? "GET";
      path = url;
      return jsonResponse({ stopped: true });
    });
    await createHttpDashboardApi().emergencyStopAll();
    expect(method).toBe("POST");
    expect(path).toBe("/api/emergency-stop");
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("surfaces escalate as unavailable and rejects without a fetch (§3)", async () => {
    const spy = stubFetch(() => jsonResponse({}));
    const api = createHttpDashboardApi();
    expect(api.escalateAvailable).toBe(false);
    await expect(api.escalateCall("call-1")).rejects.toBeInstanceOf(ControlFailure);
    expect(spy).not.toHaveBeenCalled();
  });

  it("maps a typed `{error:{message}}` body to ControlFailure.message", async () => {
    stubFetch(() => jsonResponse({ error: { message: "nope" } }, 409));
    await expect(createHttpDashboardApi().listCampaigns()).rejects.toMatchObject({
      message: "nope",
      status: 409,
    });
  });

  it("listAgents GETs /agents (api_contract.md, meta-only)", async () => {
    let path = "";
    stubFetch((url) => {
      path = url;
      return jsonResponse([{ id: "agent-demo", name: "Acme SDR", status: "ready" }]);
    });
    const agents = await createHttpDashboardApi().listAgents();
    expect(path).toBe("/api/agents");
    expect(agents).toEqual([{ id: "agent-demo", name: "Acme SDR", status: "ready" }]);
  });

  it("createCampaign POSTs the body to /campaigns and returns the Campaign", async () => {
    const campaign = makeCampaign({ id: "camp-9", name: "New one" });
    let method = "";
    let path = "";
    let body: unknown = null;
    stubFetch((url, init) => {
      method = init?.method ?? "GET";
      path = url;
      body = init?.body ? JSON.parse(String(init.body)) : null;
      return jsonResponse(campaign);
    });
    const input = {
      agent_id: "agent-demo",
      name: "New one",
      leads: [{ phone: "+15550001111", display_name: "Ada" }],
    };
    const result = await createHttpDashboardApi().createCampaign(input);
    expect(method).toBe("POST");
    expect(path).toBe("/api/campaigns");
    expect(body).toEqual(input);
    expect(result.id).toBe("camp-9");
  });
});
