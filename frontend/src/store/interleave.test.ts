import { beforeEach, describe, expect, it } from "vitest";
import { useAgentStore } from "./agentStore";
import { getPath } from "../lib/paths";
import { channelApi, makeChannel } from "../test/mocks";
import type { RawSseEvent } from "../api/sse";

const tick = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => {
  useAgentStore.setState({
    api: null,
    agentId: null,
    config: null,
    policy: [],
    materialized: {},
    flashing: {},
    messages: [],
    previewMessages: [],
    builderStreaming: false,
    previewStreaming: false,
    panelOpen: false,
  });
});

describe("builder stream interleaving (event-by-event)", () => {
  it("materializes a patch mid-stream, before the turn finishes", async () => {
    const channel = makeChannel<RawSseEvent>();
    useAgentStore.getState().init(channelApi(channel));
    await useAgentStore.getState().loadAgent("agent-demo");

    // start the turn but do not await — we drive events by hand
    const turn = useAgentStore.getState().sendBuilderMessage("hello");
    await tick();
    expect(useAgentStore.getState().builderStreaming).toBe(true);

    channel.push({ event: "token", data: { text: "One sec…" } });
    await tick();
    expect(
      useAgentStore.getState().messages.find((m) => m.role === "assistant")?.text,
    ).toBe("One sec…");
    // no patch yet -> field not materialized
    expect(useAgentStore.getState().materialized["conversation.persona.role"]).toBeUndefined();

    channel.push({
      event: "patch",
      data: { path: "conversation.persona.role", value: "SDR" },
    });
    await tick();
    // the panel field materializes WHILE the stream is still open
    const mid = useAgentStore.getState();
    expect(mid.builderStreaming).toBe(true);
    expect(getPath(mid.config, "conversation.persona.role")).toBe("SDR");
    expect(mid.materialized["conversation.persona.role"]).toBe(true);
    expect(mid.flashing["conversation.persona.role"]).toBe(true); // brief highlight

    channel.close();
    await turn;
    expect(useAgentStore.getState().builderStreaming).toBe(false);
  });
});
