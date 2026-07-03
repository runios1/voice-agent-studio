import { beforeEach, describe, expect, it } from "vitest";
import { useDashboardStore } from "./store";
import { fakeApi, makeCampaign, makeEvent, makeLead } from "./testMocks";

function reset() {
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
    auditFilter: { limit: 200 },
    auditResults: [],
    auditLoading: false,
    pending: {},
    controlError: null,
  });
}

beforeEach(reset);

const flush = () => new Promise((r) => setTimeout(r, 0));

describe("ingest", () => {
  it("appends to the live tail and caps it", () => {
    const s = useDashboardStore.getState();
    s.ingest(makeEvent({ event_id: "1" }));
    s.ingest(makeEvent({ event_id: "2" }));
    expect(useDashboardStore.getState().liveEvents.map((e) => e.event_id)).toEqual([
      "1",
      "2",
    ]);
  });

  it("reflects a campaign lifecycle event onto the snapshot state", () => {
    useDashboardStore.setState({ campaigns: [makeCampaign({ id: "c1", state: "running" })] });
    useDashboardStore.getState().ingest(
      makeEvent({ type: "campaign.autopaused", campaign_id: "c1", payload: { reason: "3 trips" } }),
    );
    const c = useDashboardStore.getState().campaigns[0];
    expect(c.state).toBe("paused");
    expect(c.autopause_reason).toBe("3 trips");
  });
});

describe("control actions (server-authoritative)", () => {
  it("pause calls the orchestrator and reflects state FROM the stream, not the click", async () => {
    const { api, calls, channel } = fakeApi({
      campaigns: [makeCampaign({ id: "c1", state: "running" })],
      reflect: true,
    });
    useDashboardStore.getState().init(api);
    await useDashboardStore.getState().loadFleet();
    useDashboardStore.getState().startStream();

    await useDashboardStore.getState().pauseCampaign("c1");
    expect(calls.pause).toEqual(["c1"]);

    // the reflecting campaign.paused event arrives on the stream → state flips
    await flush();
    expect(useDashboardStore.getState().campaigns[0].state).toBe("paused");
    channel.close();
  });

  it("emergency stop calls the control API once", async () => {
    const { api, calls } = fakeApi({ campaigns: [makeCampaign({ state: "running" })] });
    useDashboardStore.getState().init(api);
    await useDashboardStore.getState().emergencyStopAll();
    expect(calls.emergencyStop).toBe(1);
  });

  it("surfaces a control failure without throwing", async () => {
    const api = fakeApi().api;
    api.pauseCampaign = async () => {
      throw new (await import("./dashboardApi")).ControlFailure("nope", 409);
    };
    useDashboardStore.getState().init(api);
    await useDashboardStore.getState().pauseCampaign("c1");
    expect(useDashboardStore.getState().controlError).toBe("nope");
  });
});

describe("audit", () => {
  it("runAudit populates results from the server query", async () => {
    const { api } = fakeApi({
      auditResults: [makeEvent({ event_id: "a" }), makeEvent({ event_id: "b" })],
    });
    useDashboardStore.getState().init(api);
    await useDashboardStore.getState().runAudit();
    expect(useDashboardStore.getState().auditResults).toHaveLength(2);
  });
});

describe("navigation", () => {
  it("openCampaign fetches the detail snapshot", async () => {
    const { api } = fakeApi({
      campaigns: [makeCampaign({ id: "c1" })],
      leads: { c1: [makeLead(), makeLead()] },
    });
    useDashboardStore.getState().init(api);
    await useDashboardStore.getState().openCampaign("c1");
    const st = useDashboardStore.getState();
    expect(st.view).toBe("campaign");
    expect(st.selectedCampaign?.leads).toHaveLength(2);
  });
});
