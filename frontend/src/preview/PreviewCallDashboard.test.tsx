import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PreviewCallDashboard } from "./PreviewCallDashboard";
import type { Event, EventType } from "../dashboard/types";

let n = 0;
function ev(type: EventType, payload: Record<string, unknown> = {}, call_id = "call-1"): Event {
  return {
    event_id: `e-${++n}`,
    type,
    occurred_at: new Date(2026, 6, 4, 12, 0, n).toISOString(),
    severity: "info",
    tenant_id: "preview",
    campaign_id: "preview",
    lead_id: null, // preview events carry no lead_id — correlated via call_id
    call_id,
    agent_id: "a1",
    payload,
  };
}

const ROW = "lead-row-preview-call";

describe("PreviewCallDashboard", () => {
  it("shows a single Not-dialed row before any events", () => {
    render(<PreviewCallDashboard events={[]} />);
    const row = screen.getByTestId(ROW);
    expect(within(row).getByTestId("answer-not_dialed")).toBeInTheDocument();
  });

  it("fills the row in as a booked call's events arrive", () => {
    const events: Event[] = [
      ev("call.started", {}),
      ev("disclosure.spoken", { text: "AI disclosure" }),
      ev("slot.booked", { slot_start: "2026-08-01T15:00:00Z", calendar_id: "sales@acme.com" }),
      ev("tool.invoked", { tool_name: "email", params: { to: "lead@x.com" } }),
      ev("lead.outcome", { outcome: "qualified" }),
      ev("call.ended", { ended_reason: "booked" }),
    ];
    render(<PreviewCallDashboard events={events} />);

    const row = screen.getByTestId(ROW);
    // ended with a "booked" reason -> Answered; outcome -> Qualified; booking + email cells
    expect(within(row).getByTestId("answer-answered")).toBeInTheDocument();
    expect(within(row).getByText("Qualified")).toBeInTheDocument();
    expect(within(row).getByTestId("meeting-preview-call")).toBeInTheDocument();
    expect(within(row).getByTestId("email-preview-call")).toBeInTheDocument();

    // The row is expanded by default -> the what/when/where detail + timeline are visible.
    expect(screen.getByText("Meeting booked")).toBeInTheDocument();
    expect(screen.getByText("sales@acme.com")).toBeInTheDocument();
    expect(screen.getByTestId("event-feed")).toBeInTheDocument();
  });

  it("reflects an in-progress call before it ends", () => {
    render(<PreviewCallDashboard events={[ev("call.started", {})]} />);
    expect(
      within(screen.getByTestId(ROW)).getByTestId("answer-in_progress"),
    ).toBeInTheDocument();
  });
});
