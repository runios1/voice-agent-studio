import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { AgentPanel } from "./AgentPanel";
import { useAgentStore } from "../store/agentStore";
import { arrayApi } from "../test/mocks";

async function loadStore() {
  useAgentStore.setState({
    api: null, agentId: null, config: null, policy: [], materialized: {},
    flashing: {}, messages: [], previewMessages: [], builderStreaming: false,
    previewStreaming: false, panelOpen: false,
  });
  useAgentStore.getState().init(arrayApi());
  await useAgentStore.getState().loadAgent("agent-demo");
  useAgentStore.setState({ panelOpen: true }); // expand so content is in the DOM
}

beforeEach(loadStore);

describe("AgentPanel — platform section (trust feature, D11)", () => {
  it("renders the locked guardrails section from the start, read-only", () => {
    render(<AgentPanel />);
    expect(screen.getByText("🔒 Set by platform")).toBeInTheDocument();

    // a locked field shows its value but exposes NO editor
    const callingHours = screen.getByTestId("field-guardrails.calling_hours");
    expect(callingHours).toHaveTextContent("8:00 – 20:00");
    expect(callingHours.querySelector("input,select,textarea")).toBeNull();
  });

  it("lets the user tune a platform DEFAULT field (has an editor)", () => {
    render(<AgentPanel />);
    const script = screen.getByTestId("field-conversation.disclosure.disclosure_script");
    expect(script.querySelector("textarea")).not.toBeNull();
    expect(script).toHaveTextContent("default");
  });
});

describe("AgentPanel — progressive disclosure (D-UX)", () => {
  it("hides an un-decided user field, then materializes it after a patch", () => {
    render(<AgentPanel />);
    // tone not answered yet -> no row
    expect(screen.queryByTestId("field-conversation.persona.tone")).toBeNull();

    act(() => {
      useAgentStore.getState().applyPatch("conversation.persona.tone", "warm");
    });

    const tone = screen.getByTestId("field-conversation.persona.tone");
    expect(tone).toBeInTheDocument();
    expect(tone.querySelector("input")).toHaveValue("warm");
  });

  it("shows the empty-state hint before any user field is decided", () => {
    render(<AgentPanel />);
    expect(screen.getByText(/appear here as you describe/i)).toBeInTheDocument();
  });
});

describe("AgentPanel — capabilities (always-visible toggles)", () => {
  it("shows the calendar/email capability toggles even when unenabled and undecided", () => {
    render(<AgentPanel />);
    // Capability switches must be discoverable up front — not hidden behind
    // progressive disclosure like interview answers are.
    expect(screen.getByText("Capabilities")).toBeInTheDocument();
    const calendar = screen.getByTestId("field-automation.calendar");
    expect(calendar).toHaveTextContent("Calendar booking");
    const box = calendar.querySelector('input[type="checkbox"]') as HTMLInputElement;
    expect(box).not.toBeNull();
    expect(box.checked).toBe(false); // seeded draft has it off
    expect(screen.getByTestId("field-automation.email")).toBeInTheDocument();
  });
});
