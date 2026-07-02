import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CampaignView } from "./CampaignView";
import { useDashboardStore } from "./store";
import { makeCampaign, makeEvent, makeLead, mountStore, resetStore } from "./testMocks";

beforeEach(resetStore);

async function openC1(over = {}) {
  const f = await mountStore({
    campaigns: [makeCampaign({ id: "c1", name: "Alpha", ...over })],
    leads: {
      c1: [
        makeLead({ state: "done" }),
        makeLead({ state: "done" }),
        makeLead({ state: "queued" }),
        makeLead({ state: "in_call" }),
      ],
    },
  });
  await useDashboardStore.getState().openCampaign("c1");
  return f;
}

describe("CampaignView", () => {
  it("renders progress from the lead snapshot", async () => {
    await openC1();
    render(<CampaignView />);
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "50");
  });

  it("shows live calls from the stream and drills into one", async () => {
    const { channel } = await openC1();
    render(<CampaignView />);
    channel.push(makeEvent({ type: "call.started", campaign_id: "c1", call_id: "call-9" }));
    await screen.findByTestId("open-call-call-9");
    await userEvent.click(screen.getByTestId("open-call-call-9"));
    await waitFor(() => {
      expect(useDashboardStore.getState().view).toBe("live-call");
      expect(useDashboardStore.getState().selectedCallId).toBe("call-9");
    });
  });

  it("surfaces an auto-pause reason banner reflected from the stream", async () => {
    const { channel } = await openC1({ state: "running" });
    render(<CampaignView />);
    channel.push(
      makeEvent({
        type: "campaign.autopaused",
        campaign_id: "c1",
        payload: { reason: "3 trips in 5m" },
      }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("autopause-banner")).toHaveTextContent("3 trips in 5m"),
    );
  });
});
