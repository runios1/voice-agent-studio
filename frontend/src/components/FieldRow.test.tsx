import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FieldRow } from "./FieldRow";
import { useAgentStore } from "../store/agentStore";
import { arrayApi } from "../test/mocks";
import type { FieldPolicy } from "../types/contracts";

const openTone: FieldPolicy = {
  path: "conversation.persona.tone",
  owner_layer: "user",
  mutability: "open",
  required_for_ready: true,
};
const lockedDisclosure: FieldPolicy = {
  path: "conversation.disclosure.must_disclose_ai",
  owner_layer: "platform",
  mutability: "locked",
  required_for_ready: false,
};

async function loadStore(onPatch?: (...a: unknown[]) => void) {
  useAgentStore.setState({
    api: null, agentId: null, config: null, policy: [], materialized: {},
    flashing: {}, messages: [], previewMessages: [], builderStreaming: false,
    previewStreaming: false, panelOpen: false,
  });
  useAgentStore.getState().init(arrayApi({ onPatch }));
  await useAgentStore.getState().loadAgent("agent-demo");
}

describe("FieldRow manual editing", () => {
  beforeEach(() => loadStore());

  it("commits an open-field edit through PATCH /agents/{id}/fields on blur", async () => {
    const onPatch = vi.fn();
    await loadStore(onPatch);
    render(
      <div>
        <FieldRow policy={openTone} />
        <button>elsewhere</button>
      </div>,
    );

    const input = screen.getByTestId("input-conversation.persona.tone");
    await userEvent.type(input, "warm, direct");
    await userEvent.click(screen.getByText("elsewhere")); // blur -> commit

    await waitFor(() =>
      expect(onPatch).toHaveBeenCalledWith(
        "agent-demo",
        "conversation.persona.tone",
        "warm, direct",
      ),
    );
  });

  it("renders a locked field read-only with no editor", () => {
    render(<FieldRow policy={lockedDisclosure} />);
    const row = screen.getByTestId("field-conversation.disclosure.must_disclose_ai");
    expect(row.querySelector("input,select,textarea")).toBeNull();
    expect(row).toHaveTextContent("Yes"); // must_disclose_ai === true
  });
});
