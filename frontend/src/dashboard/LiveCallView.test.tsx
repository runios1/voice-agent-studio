import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { LiveCallView } from "./LiveCallView";
import { useDashboardStore } from "./store";
import { makeEvent, mountStore, resetStore } from "./testMocks";

beforeEach(resetStore);

async function selectCall(callId: string) {
  const f = await mountStore({ reflect: true });
  useDashboardStore.getState().openCall(callId);
  return f;
}

describe("LiveCallView", () => {
  it("derives 'in call' status and shows a disclosure badge from the trail", async () => {
    const { channel } = await selectCall("call-1");
    render(<LiveCallView />);
    channel.push(makeEvent({ type: "call.started", call_id: "call-1" }));
    channel.push(makeEvent({ type: "disclosure.spoken", call_id: "call-1" }));
    await waitFor(() => {
      expect(screen.getByTestId("call-status")).toHaveTextContent("in call");
      expect(screen.getByTestId("disclosure-ok")).toBeInTheDocument();
    });
  });

  it("shows transcript utterances carried on the stream", async () => {
    const { channel } = await selectCall("call-1");
    render(<LiveCallView />);
    channel.push(
      makeEvent({
        type: "disclosure.spoken",
        call_id: "call-1",
        payload: { speaker: "agent", utterance: "Hi, I'm an AI assistant." },
      }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("transcript")).toHaveTextContent("Hi, I'm an AI assistant."),
    );
  });

  it("Escalate calls the control API and disables after the call ends", async () => {
    const { channel, calls } = await selectCall("call-1");
    render(<LiveCallView />);
    channel.push(makeEvent({ type: "call.started", call_id: "call-1" }));
    await waitFor(() => expect(screen.getByTestId("escalate")).toBeEnabled());
    await userEvent.click(screen.getByTestId("escalate"));
    expect(calls.escalate).toEqual(["call-1"]);

    channel.push(makeEvent({ type: "call.ended", call_id: "call-1" }));
    await waitFor(() => expect(screen.getByTestId("escalate")).toBeDisabled());
  });
});
