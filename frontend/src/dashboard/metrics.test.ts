import { describe, expect, it } from "vitest";
import {
  activeCalls,
  applyLifecycle,
  callTrail,
  guardrailTrips,
  leadCounts,
  outcomeCounts,
  progress,
} from "./metrics";
import { makeCampaign, makeEvent, makeLead } from "./testMocks";

describe("activeCalls", () => {
  it("returns calls started but not ended, newest first, scoped by campaign", () => {
    const events = [
      makeEvent({ type: "call.started", call_id: "a", campaign_id: "c1" }),
      makeEvent({ type: "call.started", call_id: "b", campaign_id: "c1" }),
      makeEvent({ type: "call.ended", call_id: "a", campaign_id: "c1" }),
      makeEvent({ type: "call.started", call_id: "c", campaign_id: "c2" }),
    ];
    const live = activeCalls(events, "c1");
    expect(live.map((e) => e.call_id)).toEqual(["b"]); // a ended, c is other campaign
  });

  it("does not double-count a re-dialed call_id", () => {
    const events = [
      makeEvent({ type: "call.started", call_id: "a", campaign_id: "c1" }),
      makeEvent({ type: "call.started", call_id: "a", campaign_id: "c1" }),
    ];
    expect(activeCalls(events, "c1")).toHaveLength(1);
  });
});

describe("callTrail", () => {
  it("returns every event for a call, oldest-first", () => {
    const events = [
      makeEvent({ type: "call.started", call_id: "a", event_id: "1" }),
      makeEvent({ type: "call.started", call_id: "b", event_id: "2" }),
      makeEvent({ type: "disclosure.spoken", call_id: "a", event_id: "3" }),
    ];
    expect(callTrail(events, "a").map((e) => e.event_id)).toEqual(["1", "3"]);
  });
});

describe("leadCounts / progress", () => {
  it("tallies per state and computes done-fraction", () => {
    const leads = [
      makeLead({ state: "done" }),
      makeLead({ state: "done" }),
      makeLead({ state: "queued" }),
      makeLead({ state: "in_call" }),
    ];
    const counts = leadCounts(leads);
    expect(counts.done).toBe(2);
    expect(counts.queued).toBe(1);
    expect(progress(leads)).toBe(0.5);
  });

  it("progress is 0 for an empty campaign", () => {
    expect(progress([])).toBe(0);
  });
});

describe("outcomeCounts / guardrailTrips", () => {
  it("tallies outcomes and trips scoped to a campaign", () => {
    const events = [
      makeEvent({ type: "lead.outcome", campaign_id: "c1", payload: { outcome: "qualified" } }),
      makeEvent({ type: "lead.outcome", campaign_id: "c1", payload: { outcome: "qualified" } }),
      makeEvent({ type: "lead.outcome", campaign_id: "c1", payload: { outcome: "no_answer" } }),
      makeEvent({ type: "lead.outcome", campaign_id: "c2", payload: { outcome: "qualified" } }),
      makeEvent({ type: "guardrail.tripped", campaign_id: "c1" }),
      makeEvent({ type: "guardrail.tripped", campaign_id: "c1" }),
    ];
    expect(outcomeCounts(events, "c1")).toEqual({ qualified: 2, no_answer: 1 });
    expect(guardrailTrips(events, "c1")).toBe(2);
  });
});

describe("applyLifecycle", () => {
  it("reflects pause / autopause / resume onto campaign state", () => {
    const c = makeCampaign({ state: "running" });
    expect(applyLifecycle(c, makeEvent({ type: "campaign.paused" })).state).toBe("paused");

    const auto = applyLifecycle(
      c,
      makeEvent({ type: "campaign.autopaused", payload: { reason: "3 trips" } }),
    );
    expect(auto.state).toBe("paused");
    expect(auto.autopause_reason).toBe("3 trips");

    const resumed = applyLifecycle(auto, makeEvent({ type: "campaign.resumed" }));
    expect(resumed.state).toBe("running");
    expect(resumed.autopause_reason).toBeNull();
  });

  it("leaves non-lifecycle events untouched", () => {
    const c = makeCampaign({ state: "running" });
    expect(applyLifecycle(c, makeEvent({ type: "call.started" }))).toEqual(c);
  });
});
