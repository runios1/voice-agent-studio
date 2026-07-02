import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { PreviewChat } from "./PreviewChat";
import { useAgentStore } from "../store/agentStore";
import { arrayApi } from "../test/mocks";
import type { RawSseEvent } from "../api/sse";

const previewEvents: RawSseEvent[] = [
  { event: "token", data: { text: "Hi, I'm " } },
  { event: "token", data: { text: "an AI for Acme." } },
  { event: "done", data: {} },
];

beforeEach(async () => {
  useAgentStore.setState({
    api: null, agentId: null, config: null, policy: [], materialized: {},
    flashing: {}, messages: [], previewMessages: [], builderStreaming: false,
    previewStreaming: false, panelOpen: false,
  });
  useAgentStore.getState().init(arrayApi({ previewEvents }));
  await useAgentStore.getState().loadAgent("agent-demo");
});

describe("PreviewChat — talk TO the agent (runtime loop)", () => {
  it("streams the agent's reply into the preview transcript", async () => {
    render(<PreviewChat />);
    await userEvent.type(screen.getByTestId("composer-input"), "hello");
    await userEvent.click(screen.getByTestId("composer-send"));

    await waitFor(() =>
      expect(screen.getByTestId("msg-assistant")).toHaveTextContent(
        "Hi, I'm an AI for Acme.",
      ),
    );
    // the user's turn is echoed too
    expect(screen.getByTestId("msg-user")).toHaveTextContent("hello");
  });
});
