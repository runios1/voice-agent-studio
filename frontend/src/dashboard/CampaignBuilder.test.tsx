import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CampaignBuilder } from "./CampaignBuilder";
import { useDashboardStore } from "./store";
import { makeAgentSummary, mountStore, resetStore } from "./testMocks";

beforeEach(resetStore);

async function goToLeads() {
  await userEvent.click(await screen.findByTestId("agent-select"));
  await userEvent.selectOptions(screen.getByTestId("agent-select"), "agent-demo");
  await userEvent.type(screen.getByTestId("campaign-name"), "West-coast SaaS Q3");
  await userEvent.click(screen.getByTestId("next-to-leads"));
}

describe("CampaignBuilder", () => {
  it("blocks proceeding past setup until an agent + name are chosen", async () => {
    await mountStore({ agents: [makeAgentSummary()] });
    render(<CampaignBuilder />);
    await screen.findByTestId("agent-select");
    expect(screen.getByTestId("next-to-leads")).toBeDisabled();
    await userEvent.selectOptions(screen.getByTestId("agent-select"), "agent-demo");
    expect(screen.getByTestId("next-to-leads")).toBeDisabled();
    await userEvent.type(screen.getByTestId("campaign-name"), "Q3");
    expect(screen.getByTestId("next-to-leads")).not.toBeDisabled();
  });

  it("warns and blocks when the only agent isn't deploy-ready", async () => {
    await mountStore({ agents: [makeAgentSummary({ id: "a-draft", status: "draft" })] });
    render(<CampaignBuilder />);
    await screen.findByTestId("agent-select");
    await userEvent.selectOptions(screen.getByTestId("agent-select"), "a-draft");
    await userEvent.type(screen.getByTestId("campaign-name"), "Q3");
    expect(screen.getByText(/isn't deploy-ready yet/)).toBeInTheDocument();
    expect(screen.getByTestId("next-to-leads")).toBeDisabled();
  });

  it("adds a manual lead and rejects an invalid phone number", async () => {
    await mountStore({ agents: [makeAgentSummary()] });
    render(<CampaignBuilder />);
    await goToLeads();

    await userEvent.type(screen.getByTestId("lead-phone"), "not-a-phone");
    await userEvent.click(screen.getByTestId("add-lead"));
    expect(screen.getByText(/valid phone number/)).toBeInTheDocument();

    await userEvent.clear(screen.getByTestId("lead-phone"));
    await userEvent.type(screen.getByTestId("lead-phone"), "+15550001111");
    await userEvent.type(screen.getByTestId("lead-name"), "Ada Lovelace");
    await userEvent.click(screen.getByTestId("add-lead"));

    expect(screen.getByTestId("lead-list")).toHaveTextContent("+15550001111");
    expect(screen.getByTestId("lead-list")).toHaveTextContent("Ada Lovelace");
  });

  it("imports CSV leads and reports skipped rows without dropping the batch", async () => {
    await mountStore({ agents: [makeAgentSummary()] });
    render(<CampaignBuilder />);
    await goToLeads();

    fireEvent.change(screen.getByTestId("csv-text"), {
      target: { value: "phone,name\nnot-a-number,Bad\n+15550002222,Grace Hopper" },
    });
    await userEvent.click(screen.getByTestId("import-csv"));

    expect(screen.getByTestId("lead-list")).toHaveTextContent("+15550002222");
    expect(screen.getByTestId("invalid-rows")).toHaveTextContent("not a valid phone number");
  });

  it("removes a lead from the list", async () => {
    await mountStore({ agents: [makeAgentSummary()] });
    render(<CampaignBuilder />);
    await goToLeads();
    await userEvent.type(screen.getByTestId("lead-phone"), "+15550001111");
    await userEvent.click(screen.getByTestId("add-lead"));
    await userEvent.click(screen.getByTestId("remove-lead-+15550001111"));
    expect(screen.getByText("No leads added yet.")).toBeInTheDocument();
  });

  it("requires the explicit checkbox before Authorize is enabled, then submits", async () => {
    const { calls } = await mountStore({ agents: [makeAgentSummary()] });
    render(<CampaignBuilder />);
    await goToLeads();
    await userEvent.type(screen.getByTestId("lead-phone"), "+15550001111");
    await userEvent.click(screen.getByTestId("add-lead"));
    await userEvent.click(screen.getByTestId("next-to-review"));

    expect(screen.getByTestId("review-lead-count")).toHaveTextContent("1");
    expect(screen.getByTestId("authorize-campaign")).toBeDisabled();

    await userEvent.click(screen.getByTestId("authorize-checkbox"));
    expect(screen.getByTestId("authorize-campaign")).not.toBeDisabled();

    await userEvent.click(screen.getByTestId("authorize-campaign"));

    await waitFor(() => expect(calls.createCampaign).toHaveLength(1));
    expect(calls.createCampaign[0]).toMatchObject({
      agent_id: "agent-demo",
      name: "West-coast SaaS Q3",
      leads: [{ phone: "+15550001111", display_name: undefined }],
    });
    // Successful authorize navigates into the new campaign's detail view.
    await waitFor(() => expect(useDashboardStore.getState().view).toBe("campaign"));
  });

  it("surfaces a server rejection on the review step without losing the form", async () => {
    await mountStore({
      agents: [makeAgentSummary()],
      createCampaign: async () => {
        throw new (await import("./dashboardApi")).ControlFailure("Leads exceed plan limit.", 422);
      },
    });
    useDashboardStore.getState().openNewCampaign();
    render(<CampaignBuilder />);
    await goToLeads();
    await userEvent.type(screen.getByTestId("lead-phone"), "+15550001111");
    await userEvent.click(screen.getByTestId("add-lead"));
    await userEvent.click(screen.getByTestId("next-to-review"));
    await userEvent.click(screen.getByTestId("authorize-checkbox"));
    await userEvent.click(screen.getByTestId("authorize-campaign"));

    await screen.findByText("Leads exceed plan limit.");
    expect(useDashboardStore.getState().view).toBe("new-campaign");
    expect(screen.getByTestId("review-lead-count")).toHaveTextContent("1");
  });

  it("Cancel returns to the fleet view", async () => {
    await mountStore({ agents: [makeAgentSummary()] });
    useDashboardStore.getState().openNewCampaign();
    render(<CampaignBuilder />);
    await screen.findByTestId("agent-select");
    await userEvent.click(screen.getByTestId("cancel-builder"));
    expect(useDashboardStore.getState().view).toBe("fleet");
  });
});
