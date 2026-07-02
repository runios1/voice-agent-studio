import { beforeEach, describe, expect, it, vi } from "vitest";
import { seedMaterialized, useAgentStore } from "./agentStore";
import { getPath } from "../lib/paths";
import { FIELD_POLICY, makeSeededDraft } from "../fixtures/agentFixture";
import { arrayApi } from "../test/mocks";
import type { RawSseEvent } from "../api/sse";

function reset() {
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
}

beforeEach(reset);

describe("seedMaterialized", () => {
  it("materializes only user string/list fields that have content", () => {
    const cfg = makeSeededDraft();
    cfg.conversation.persona.role = "SDR for Acme"; // string -> materialized
    cfg.conversation.objections = [{ trigger: "no time", response_guidance: "be brief" }];
    const seeded = seedMaterialized(cfg, FIELD_POLICY);
    expect(seeded["conversation.persona.role"]).toBe(true);
    expect(seeded["conversation.objections"]).toBe(true);
    // untouched user fields stay hidden
    expect(seeded["conversation.persona.tone"]).toBeUndefined();
    // enum with a schema default must NOT auto-materialize (no empty selector rule)
    expect(seeded["conversation.voicemail.action"]).toBeUndefined();
    // platform fields are never in the user-materialized set
    expect(seeded["guardrails.calling_hours"]).toBeUndefined();
  });
});

describe("loadAgent", () => {
  it("loads config + policy and seeds materialization", async () => {
    useAgentStore.getState().init(arrayApi());
    await useAgentStore.getState().loadAgent("agent-demo");
    const s = useAgentStore.getState();
    expect(s.config?.meta.id).toBe("agent-demo");
    expect(s.policy).toHaveLength(FIELD_POLICY.length);
  });
});

describe("sendBuilderMessage — token/patch/notice interleaving", () => {
  const events: RawSseEvent[] = [
    { event: "token", data: { text: "Setting " } },
    { event: "token", data: { text: "your role." } },
    { event: "patch", data: { path: "conversation.persona.role", value: "SDR for Acme" } },
    { event: "notice", data: { message: "AI disclosure can't be disabled." } },
    { event: "done", data: {} },
  ];

  it("streams tokens into one bubble, materializes the patch, appends the notice", async () => {
    useAgentStore.getState().init(arrayApi({ builderEvents: events }));
    await useAgentStore.getState().loadAgent("agent-demo");
    await useAgentStore.getState().sendBuilderMessage("Build an SDR for Acme");

    const s = useAgentStore.getState();
    const roles = s.messages.map((m) => m.role);
    expect(roles).toEqual(["user", "assistant", "notice"]);

    const assistant = s.messages.find((m) => m.role === "assistant")!;
    expect(assistant.text).toBe("Setting your role.");
    expect(assistant.streaming).toBe(false);

    // patch materialized the panel field + updated the shared config
    expect(getPath(s.config, "conversation.persona.role")).toBe("SDR for Acme");
    expect(s.materialized["conversation.persona.role"]).toBe(true);

    // notice surfaced conversationally, not as a patch
    expect(s.messages.at(-1)?.text).toContain("AI disclosure");
    expect(s.builderStreaming).toBe(false);
  });
});

describe("editField — server-authoritative", () => {
  it("applies an accepted open-field edit only after PATCH resolves", async () => {
    const onPatch = vi.fn();
    useAgentStore.getState().init(arrayApi({ onPatch }));
    await useAgentStore.getState().loadAgent("agent-demo");

    await useAgentStore.getState().editField("conversation.persona.tone", "friendly");

    expect(onPatch).toHaveBeenCalledWith("agent-demo", "conversation.persona.tone", "friendly");
    const s = useAgentStore.getState();
    expect(getPath(s.config, "conversation.persona.tone")).toBe("friendly");
    expect(s.materialized["conversation.persona.tone"]).toBe(true);
    expect(s.messages).toHaveLength(0); // no notice on success
  });

  it("rejects a locked-path edit with a conversational notice and leaves config unchanged", async () => {
    useAgentStore.getState().init(arrayApi());
    await useAgentStore.getState().loadAgent("agent-demo");
    const before = getPath(
      useAgentStore.getState().config,
      "conversation.disclosure.must_disclose_ai",
    );

    await useAgentStore
      .getState()
      .editField("conversation.disclosure.must_disclose_ai", false);

    const s = useAgentStore.getState();
    expect(getPath(s.config, "conversation.disclosure.must_disclose_ai")).toBe(before);
    expect(s.messages.at(-1)?.role).toBe("notice");
    expect(s.messages.at(-1)?.text).toContain("locked");
  });
});
