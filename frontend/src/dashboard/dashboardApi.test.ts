import { describe, expect, it } from "vitest";
import { filterToQuery, rawToEvent } from "./dashboardApi";
import { makeEvent } from "./testMocks";

describe("filterToQuery", () => {
  it("serializes only the set fields", () => {
    const q = new URLSearchParams(
      filterToQuery({ types: ["call.started", "call.ended"], severity: "warning", limit: 50 }),
    );
    expect(q.get("types")).toBe("call.started,call.ended");
    expect(q.get("severity")).toBe("warning");
    expect(q.get("limit")).toBe("50");
    expect(q.get("campaign_id")).toBeNull();
  });

  it("is empty for an empty filter", () => {
    expect(filterToQuery({})).toBe("");
  });
});

describe("rawToEvent", () => {
  it("accepts a parsed Event object regardless of the SSE `event:` label", () => {
    const ev = makeEvent({ event_id: "x", type: "slot.booked" });
    expect(rawToEvent({ event: "slot.booked", data: ev })?.event_id).toBe("x");
    expect(rawToEvent({ event: "message", data: ev })?.type).toBe("slot.booked");
  });

  it("rejects records that aren't events", () => {
    expect(rawToEvent({ event: "ping", data: "keep-alive" })).toBeNull();
    expect(rawToEvent({ event: "message", data: { foo: 1 } })).toBeNull();
  });
});
