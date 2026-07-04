import { describe, expect, it } from "vitest";
import {
  activeCalls,
  applyLifecycle,
  buildLeadRecords,
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

describe("buildLeadRecords", () => {
  it("folds a full call trail onto a lead: dialed, answered, qualified, booked, emailed", () => {
    const lead = makeLead({ id: "L1", state: "done", attempts: 1, outcome: "qualified", last_call_id: "call-1" });
    const events = [
      makeEvent({ type: "call.started", lead_id: "L1", call_id: "call-1", payload: { to_number: "+15551112222" } }),
      makeEvent({ type: "disclosure.spoken", lead_id: "L1", call_id: "call-1", payload: { text: "AI here" } }),
      makeEvent({ type: "slot.booked", lead_id: "L1", call_id: "call-1", payload: { slot_start: "2026-02-01T15:00:00Z", calendar_id: "cal-x" } }),
      makeEvent({ type: "tool.invoked", lead_id: "L1", call_id: "call-1", payload: { tool_name: "email", params: { to: "a@x.com" }, result_status: "ok" } }),
      makeEvent({ type: "call.ended", lead_id: "L1", call_id: "call-1", payload: { ended_reason: "completed" } }),
    ];
    const [r] = buildLeadRecords([lead], events);
    expect(r.dialed).toBe(true);
    expect(r.answer).toBe("answered");
    expect(r.qualified).toBe(true);
    expect(r.disclosed).toBe(true);
    expect(r.booking?.start).toBe("2026-02-01T15:00:00Z");
    expect(r.booking?.where).toBe("cal-x");
    expect(r.email?.to).toBe("a@x.com");
    expect(r.toNumber).toBe("+15551112222");
    expect(r.events).toHaveLength(5);
  });

  it("classifies no-answer, voicemail and not-dialed", () => {
    const leads = [
      makeLead({ id: "A", state: "retry", attempts: 1 }),
      makeLead({ id: "B", state: "retry", attempts: 1 }),
      makeLead({ id: "C", state: "queued", attempts: 0 }),
    ];
    const events = [
      makeEvent({ type: "call.ended", lead_id: "A", call_id: "ca", payload: { ended_reason: "no_answer" } }),
      makeEvent({ type: "call.ended", lead_id: "B", call_id: "cb", payload: { ended_reason: "voicemail" } }),
    ];
    const [a, b, c] = buildLeadRecords(leads, events);
    expect(a.answer).toBe("no_answer");
    expect(b.answer).toBe("voicemail");
    expect(c.answer).toBe("not_dialed");
    expect(c.dialed).toBe(false);
  });

  it("attributes call-scoped events without lead_id via last_call_id", () => {
    const lead = makeLead({ id: "L1", state: "done", attempts: 1, outcome: "not_qualified", last_call_id: "call-9" });
    // No lead_id on the events — only call_id, matched through last_call_id.
    const events = [
      makeEvent({ type: "call.started", call_id: "call-9" }),
      makeEvent({ type: "call.ended", call_id: "call-9", payload: { ended_reason: "completed" } }),
    ];
    const [r] = buildLeadRecords([lead], events);
    expect(r.events).toHaveLength(2);
    expect(r.answer).toBe("answered");
    expect(r.qualified).toBe(false);
  });

  it("prefers the snapshot outcome but falls back to the lead.outcome event", () => {
    const lead = makeLead({ id: "L1", state: "outcome", attempts: 1 });
    const events = [
      makeEvent({ type: "lead.outcome", lead_id: "L1", payload: { outcome: "qualified" } }),
    ];
    const [r] = buildLeadRecords([lead], events);
    expect(r.outcome).toBe("qualified");
    expect(r.qualified).toBe(true);
  });

  it("counts a booked meeting as qualified (orchestrator records outcome 'booked')", () => {
    // The real state machine (resolve_outcome) stores a booked lead's outcome as
    // "booked"; the row must still read as Qualified.
    const lead = makeLead({ id: "L1", state: "done", attempts: 1, outcome: "booked" });
    const [r] = buildLeadRecords([lead], []);
    expect(r.qualified).toBe(true);
  });
});
