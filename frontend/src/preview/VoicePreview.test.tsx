import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { VoicePreview } from "./VoicePreview";
import type { VoiceSessionCallbacks } from "./voiceSession";

/** VoicePreview only needs to react to VoiceSession's callbacks correctly — the
 * session itself (WS wire format, mic, playback) is unit-tested in
 * voiceSession.test.ts against a fake WS. Here we fake the session class so the
 * component test can drive it without a browser mic/AudioContext/WebSocket. */
class FakeSession {
  static instances: FakeSession[] = [];
  started = false;
  stopped = false;
  constructor(
    public agentId: string,
    public callbacks: VoiceSessionCallbacks,
  ) {
    FakeSession.instances.push(this);
  }
  start() {
    this.started = true;
    return Promise.resolve();
  }
  stop() {
    this.stopped = true;
    this.callbacks.onStatus?.("ended");
  }
}

vi.mock("./voiceSession", () => ({
  VoiceSession: vi.fn(
    (agentId: string, callbacks: VoiceSessionCallbacks) => new FakeSession(agentId, callbacks),
  ),
}));

beforeEach(() => {
  FakeSession.instances.length = 0;
});

describe("VoicePreview", () => {
  it("starts a session on Talk and renders transcript/disclosure/outcome from callbacks", async () => {
    render(<VoicePreview agentId="agent-1" />);
    await userEvent.click(screen.getByTestId("talk-button"));

    const session = FakeSession.instances[0];
    expect(session.agentId).toBe("agent-1");
    expect(session.started).toBe(true);

    act(() => {
      session.callbacks.onStatus?.("live");
      session.callbacks.onDisclosure?.();
      session.callbacks.onTranscript?.("agent", "Hi, this is an AI assistant calling for Acme.");
      session.callbacks.onOutcome?.("booked");
    });

    await waitFor(() => expect(screen.getByTestId("hang-up")).toBeInTheDocument());
    expect(screen.getByTestId("disclosure-badge")).toHaveTextContent("AI disclosed");
    expect(screen.getByTestId("voice-line-agent")).toHaveTextContent(
      "Hi, this is an AI assistant",
    );
    expect(screen.getByTestId("voice-outcome")).toHaveTextContent("booked");
  });

  it("shows a calm inline error on mic-permission denial, never a stack trace", async () => {
    render(<VoicePreview agentId="agent-1" />);
    await userEvent.click(screen.getByTestId("talk-button"));
    const session = FakeSession.instances[0];

    act(() => {
      session.callbacks.onStatus?.("error");
      session.callbacks.onError?.(
        "Couldn't access your microphone — check your browser permissions and try again.",
      );
    });

    await waitFor(() =>
      expect(screen.getByTestId("voice-error")).toHaveTextContent(
        "Couldn't access your microphone",
      ),
    );
    // back to the idle affordance so the user can retry
    expect(screen.getByTestId("talk-button")).toBeInTheDocument();
  });

  it("Hang up calls session.stop()", async () => {
    render(<VoicePreview agentId="agent-1" />);
    await userEvent.click(screen.getByTestId("talk-button"));
    const session = FakeSession.instances[0];
    act(() => {
      session.callbacks.onStatus?.("live");
    });

    await waitFor(() => screen.getByTestId("hang-up"));
    await userEvent.click(screen.getByTestId("hang-up"));

    expect(session.stopped).toBe(true);
  });
});
