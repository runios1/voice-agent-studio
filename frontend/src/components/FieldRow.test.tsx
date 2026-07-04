import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FieldRow } from "./FieldRow";
import { useAgentStore } from "../store/agentStore";
import { useConnectionsStore } from "../connections/connectionsStore";
import { arrayApi } from "../test/mocks";
import type { FieldPolicy } from "../types/contracts";
import type { ConnectionInfo } from "../connections/connectionsApi";

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
const calendarCapability: FieldPolicy = {
  path: "automation.calendar",
  owner_layer: "user",
  mutability: "open",
  required_for_ready: false,
};
const emailCapability: FieldPolicy = {
  path: "automation.email",
  owner_layer: "user",
  mutability: "open",
  required_for_ready: false,
};

const conn = (provider: string, connected: boolean): ConnectionInfo => ({
  provider,
  connected,
  scopes: [],
  connection_ref: connected ? `ref-${provider}` : null,
});

/** Seed the (module-singleton) connections store, marked loaded so gating engages. */
function setConnections(...cs: ConnectionInfo[]) {
  useConnectionsStore.setState({
    byProvider: Object.fromEntries(cs.map((c) => [c.provider, c])),
    loaded: true,
  });
}

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

  it("renders a capability block as an off toggle and enables it via its .enabled leaf", async () => {
    const onPatch = vi.fn();
    await loadStore(onPatch);
    render(<FieldRow policy={calendarCapability} />);

    // seeded draft has calendar disabled -> unchecked
    const box = screen.getByTestId("input-automation.calendar") as HTMLInputElement;
    expect(box.checked).toBe(false);

    await userEvent.click(box); // flip on

    await waitFor(() =>
      expect(onPatch).toHaveBeenCalledWith(
        "agent-demo",
        "automation.calendar.enabled", // patches the boolean leaf, not the object
        true,
      ),
    );
  });
});

describe("FieldRow capability connection gating", () => {
  beforeEach(() => loadStore());
  // The connections store is a module singleton; reset it so tests don't leak.
  afterEach(() => useConnectionsStore.setState({ byProvider: {}, loaded: false }));

  it("disables a capability whose provider isn't connected and links to Connections", async () => {
    await loadStore();
    setConnections(conn("gmail", false));
    render(<FieldRow policy={emailCapability} />);

    const box = screen.getByTestId("input-automation.email") as HTMLInputElement;
    expect(box.disabled).toBe(true);

    const link = screen.getByTestId("connect-link-automation.email");
    expect(link).toHaveAttribute("href", "/dashboard.html#connections");
    expect(link).toHaveTextContent(/Connect Gmail/i);
  });

  it("leaves the toggle enabled once the provider is connected", async () => {
    await loadStore();
    setConnections(conn("gmail", true));
    render(<FieldRow policy={emailCapability} />);

    const box = screen.getByTestId("input-automation.email") as HTMLInputElement;
    expect(box.disabled).toBe(false);
    expect(screen.queryByTestId("connect-link-automation.email")).toBeNull();
  });
});
