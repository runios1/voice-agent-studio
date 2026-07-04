import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CampaignCallDetails } from "./CampaignCallDetails";
import { useDashboardStore } from "./store";
import { makeCampaign, makeEvent, makeLead, mountStore, resetStore } from "./testMocks";

beforeEach(resetStore);

/** Open a campaign whose durable history (audit) is the given events. */
async function openWith(leads = defaultLeads(), auditResults = defaultHistory()) {
  const f = await mountStore({
    campaigns: [makeCampaign({ id: "c1", name: "Alpha" })],
    leads: { c1: leads },
    auditResults,
  });
  await useDashboardStore.getState().openCampaign("c1");
  return f;
}

function defaultLeads() {
  return [
    makeLead({ id: "c1-lead-0", display_name: "Ann", phone: "+15550000001", state: "done", attempts: 1, outcome: "qualified", last_call_id: "call-a" }),
    makeLead({ id: "c1-lead-1", display_name: "Bob", phone: "+15550000002", state: "done", attempts: 2, outcome: "not_qualified", last_call_id: "call-b" }),
    makeLead({ id: "c1-lead-2", display_name: "Cy", phone: "+15550000003", state: "queued", attempts: 0 }),
  ];
}

function defaultHistory() {
  return [
    makeEvent({ type: "call.started", campaign_id: "c1", lead_id: "c1-lead-0", call_id: "call-a", payload: { to_number: "+15550000001" }, occurred_at: "2026-01-01T10:00:00Z" }),
    makeEvent({ type: "disclosure.spoken", campaign_id: "c1", lead_id: "c1-lead-0", call_id: "call-a", payload: { text: "AI here" }, occurred_at: "2026-01-01T10:00:05Z" }),
    makeEvent({ type: "slot.booked", campaign_id: "c1", lead_id: "c1-lead-0", call_id: "call-a", payload: { slot_start: "2026-02-01T15:00:00Z", calendar_id: "sales@acme.com" }, occurred_at: "2026-01-01T10:01:00Z" }),
    makeEvent({ type: "tool.invoked", campaign_id: "c1", lead_id: "c1-lead-0", call_id: "call-a", payload: { tool_name: "email", params: { to: "ann@x.com" }, result_status: "ok" }, occurred_at: "2026-01-01T10:01:10Z" }),
    makeEvent({ type: "call.ended", campaign_id: "c1", lead_id: "c1-lead-0", call_id: "call-a", payload: { ended_reason: "completed" }, occurred_at: "2026-01-01T10:02:00Z" }),
    // Bob: dialed, no answer.
    makeEvent({ type: "call.started", campaign_id: "c1", lead_id: "c1-lead-1", call_id: "call-b", occurred_at: "2026-01-01T10:03:00Z" }),
    makeEvent({ type: "call.ended", campaign_id: "c1", lead_id: "c1-lead-1", call_id: "call-b", payload: { ended_reason: "no_answer" }, occurred_at: "2026-01-01T10:03:30Z" }),
  ];
}

describe("CampaignCallDetails", () => {
  it("summarizes dialed / answered / qualified / meetings / emails", async () => {
    await openWith();
    render(<CampaignCallDetails />);
    const summary = await screen.findByTestId("detail-summary");
    // 3 leads, 2 dialed, 1 answered, 1 qualified, 1 meeting, 1 email.
    expect(within(summary).getByText("Leads").nextSibling).toHaveTextContent("3");
    expect(within(summary).getByText("Dialed").nextSibling).toHaveTextContent("2");
    expect(within(summary).getByText("Answered").nextSibling).toHaveTextContent("1");
    expect(within(summary).getByText("Qualified").nextSibling).toHaveTextContent("1");
    expect(within(summary).getByText("Meetings").nextSibling).toHaveTextContent("1");
    expect(within(summary).getByText("Emails").nextSibling).toHaveTextContent("1");
  });

  it("shows per-lead answer, qualification, meeting and email columns", async () => {
    await openWith();
    render(<CampaignCallDetails />);
    await screen.findByTestId("lead-row-c1-lead-0");
    const ann = screen.getByTestId("lead-row-c1-lead-0");
    expect(within(ann).getByTestId("answer-answered")).toBeInTheDocument();
    expect(within(ann).getByText("Qualified")).toBeInTheDocument();
    expect(within(ann).getByTestId("meeting-c1-lead-0")).toBeInTheDocument();
    expect(within(ann).getByTestId("email-c1-lead-0")).toBeInTheDocument();

    const bob = screen.getByTestId("lead-row-c1-lead-1");
    expect(within(bob).getByTestId("answer-no_answer")).toBeInTheDocument();
    expect(within(bob).getByText("Not qualified")).toBeInTheDocument();

    const cy = screen.getByTestId("lead-row-c1-lead-2");
    expect(within(cy).getByTestId("answer-not_dialed")).toBeInTheDocument();
  });

  it("expands a lead to reveal the what/when/where detail and timeline", async () => {
    await openWith();
    render(<CampaignCallDetails />);
    await screen.findByTestId("lead-row-c1-lead-0");
    await userEvent.click(screen.getByTestId("lead-row-c1-lead-0"));
    expect(await screen.findByText("Number dialed")).toBeInTheDocument();
    expect(screen.getByText("Meeting booked")).toBeInTheDocument();
    expect(screen.getByText("Meeting on")).toBeInTheDocument();
    expect(screen.getByText("sales@acme.com")).toBeInTheDocument();
    // Timeline reuses the shared EventFeed.
    expect(screen.getByTestId("event-feed")).toBeInTheDocument();
  });

  it("filters by search and by outcome", async () => {
    await openWith();
    render(<CampaignCallDetails />);
    await screen.findByTestId("lead-row-c1-lead-0");

    await userEvent.type(screen.getByTestId("lead-search"), "Bob");
    await waitFor(() => {
      expect(screen.queryByTestId("lead-row-c1-lead-0")).not.toBeInTheDocument();
      expect(screen.getByTestId("lead-row-c1-lead-1")).toBeInTheDocument();
    });

    await userEvent.clear(screen.getByTestId("lead-search"));
    await userEvent.selectOptions(screen.getByTestId("outcome-filter"), "qualified");
    await waitFor(() => {
      expect(screen.getByTestId("lead-row-c1-lead-0")).toBeInTheDocument();
      expect(screen.queryByTestId("lead-row-c1-lead-1")).not.toBeInTheDocument();
    });
  });

  it("merges a live event on top of the loaded history", async () => {
    const { channel } = await openWith();
    render(<CampaignCallDetails />);
    await screen.findByTestId("lead-row-c1-lead-2");
    // Cy was queued/not dialed; a live call.started should flip its answer cell.
    expect(
      within(screen.getByTestId("lead-row-c1-lead-2")).getByTestId("answer-not_dialed"),
    ).toBeInTheDocument();
    channel.push(
      makeEvent({ type: "call.started", campaign_id: "c1", lead_id: "c1-lead-2", call_id: "call-c" }),
    );
    await waitFor(() =>
      expect(
        within(screen.getByTestId("lead-row-c1-lead-2")).getByTestId("answer-in_progress"),
      ).toBeInTheDocument(),
    );
  });
});
