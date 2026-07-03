import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { PreviewChat } from "./PreviewChat";
import { useAgentStore } from "../store/agentStore";
import { arrayApi } from "../test/mocks";

beforeEach(async () => {
  useAgentStore.setState({
    api: null, agentId: null, config: null, policy: [], materialized: {},
    flashing: {}, messages: [], previewMessages: [], builderStreaming: false,
    previewStreaming: false, panelOpen: false,
  });
  useAgentStore.getState().init(arrayApi({}));
  await useAgentStore.getState().loadAgent("agent-demo");
});

describe("PreviewChat — talk TO the agent (live voice only)", () => {
  it("renders the Live voice preview, not a text chat surface", () => {
    render(<PreviewChat />);
    expect(screen.getByTestId("live-voice-preview")).toBeInTheDocument();
    // the old text preview composer is gone
    expect(screen.queryByTestId("composer-input")).not.toBeInTheDocument();
  });
});
