import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { FleetView } from "./FleetView";
import { useDashboardStore } from "./store";
import { makeCampaign, makeEvent, mountStore, resetStore } from "./testMocks";

beforeEach(resetStore);

describe("FleetView", () => {
  it("renders every campaign with its state", async () => {
    await mountStore({
      campaigns: [
        makeCampaign({ id: "c1", name: "Alpha", state: "running" }),
        makeCampaign({ id: "c2", name: "Beta", state: "paused" }),
      ],
    });
    render(<FleetView />);
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(screen.getByTestId("campaign-state-running")).toBeInTheDocument();
    expect(screen.getByTestId("campaign-state-paused")).toBeInTheDocument();
  });

  it("reflects a live call.started as an incremented live-call count", async () => {
    const { channel } = await mountStore({
      campaigns: [makeCampaign({ id: "c1", name: "Alpha", state: "running" })],
    });
    render(<FleetView />);
    const cell = () => screen.getByTestId("fleet-row-c1").querySelectorAll("td")[2];
    expect(cell()).toHaveTextContent("0");
    channel.push(makeEvent({ type: "call.started", campaign_id: "c1", call_id: "x" }));
    await waitFor(() => expect(cell()).toHaveTextContent("1"));
  });

  it("Pause calls the orchestrator and the stream flips the state", async () => {
    const { calls } = await mountStore({
      campaigns: [makeCampaign({ id: "c1", name: "Alpha", state: "running" })],
      reflect: true,
    });
    render(<FleetView />);
    await userEvent.click(screen.getByTestId("pause-c1"));
    expect(calls.pause).toEqual(["c1"]);
    await waitFor(() =>
      expect(screen.getByTestId("campaign-state-paused")).toBeInTheDocument(),
    );
  });

  it("disables the global emergency stop when nothing is running", async () => {
    await mountStore({ campaigns: [makeCampaign({ id: "c1", state: "completed" })] });
    render(<FleetView />);
    expect(screen.getByTestId("emergency-stop")).toBeDisabled();
  });

  it("global emergency stop calls the control API when a campaign is running", async () => {
    const { calls } = await mountStore({
      campaigns: [makeCampaign({ id: "c1", state: "running" })],
    });
    render(<FleetView />);
    await userEvent.click(screen.getByTestId("emergency-stop"));
    expect(calls.emergencyStop).toBe(1);
  });

  it("clicking a campaign drills into the campaign view", async () => {
    await mountStore({ campaigns: [makeCampaign({ id: "c1", name: "Alpha" })] });
    render(<FleetView />);
    await userEvent.click(screen.getByTestId("open-campaign-c1"));
    await waitFor(() => expect(useDashboardStore.getState().view).toBe("campaign"));
  });
});
