import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LiveVoicePreview } from "./LiveVoicePreview";
import type { LiveVoiceSessionCallbacks } from "./liveVoiceSession";

/** LiveVoicePreview only needs to react to LiveVoiceSession's callbacks correctly
 * — the session itself (WS wire format, mic, playback, indicator inference) is
 * unit-tested in liveVoiceSession.test.ts against a fake WS. Here we fake the
 * session class so the component test can drive it without a browser
 * mic/AudioContext/WebSocket. */
class FakeSession {
  static instances: FakeSession[] = [];
  started = false;
  stopped = false;
  constructor(
    public agentId: string,
    public callbacks: LiveVoiceSessionCallbacks,
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

vi.mock("./liveVoiceSession", () => ({
  LiveVoiceSession: vi.fn(
    (agentId: string, callbacks: LiveVoiceSessionCallbacks) => new FakeSession(agentId, callbacks),
  ),
}));

beforeEach(() => {
  FakeSession.instances.length = 0;
});

describe("LiveVoicePreview", () => {
  it("starts a session on Talk and renders transcript/disclosure/outcome", async () => {
    render(<LiveVoicePreview agentId="agent-1" />);
    await userEvent.click(screen.getByTestId("live-talk-button"));

    const session = FakeSession.instances[0];
    expect(session.agentId).toBe("agent-1");
    expect(session.started).toBe(true);

    act(() => {
      session.callbacks.onStatus?.("live");
      session.callbacks.onDisclosure?.();
      session.callbacks.onTranscript?.("agent", "Hi, this is an AI assistant calling for Acme.");
      session.callbacks.onOutcome?.("booked");
    });

    await waitFor(() => expect(screen.getByTestId("live-hang-up")).toBeInTheDocument());
    expect(screen.getByTestId("disclosure-badge")).toHaveTextContent("AI disclosed");
    expect(screen.getByTestId("live-line-agent")).toHaveTextContent(
      "Hi, this is an AI assistant",
    );
    expect(screen.getByTestId("live-outcome")).toHaveTextContent("booked");
  });

  it("renders the speaking/listening indicator from onIndicator", async () => {
    render(<LiveVoicePreview agentId="agent-1" />);
    await userEvent.click(screen.getByTestId("live-talk-button"));
    const session = FakeSession.instances[0];

    act(() => {
      session.callbacks.onStatus?.("live");
      session.callbacks.onIndicator?.("agent");
    });
    await waitFor(() =>
      expect(screen.getByTestId("speaking-indicator")).toHaveTextContent("Agent speaking"),
    );

    act(() => {
      session.callbacks.onIndicator?.("listening");
    });
    expect(screen.getByTestId("speaking-indicator")).toHaveTextContent("Listening");
  });

  it("renders a tool badge on onTool", async () => {
    render(<LiveVoicePreview agentId="agent-1" />);
    await userEvent.click(screen.getByTestId("live-talk-button"));
    const session = FakeSession.instances[0];

    act(() => {
      session.callbacks.onStatus?.("live");
      session.callbacks.onTool?.("calendar", "in_call");
    });

    expect(screen.getByTestId("live-line-tool")).toHaveTextContent("calendar");
  });

  it("renders a moderation badge on onModeration, styled by verdict", async () => {
    render(<LiveVoicePreview agentId="agent-1" />);
    await userEvent.click(screen.getByTestId("live-talk-button"));
    const session = FakeSession.instances[0];

    act(() => {
      session.callbacks.onStatus?.("live");
      session.callbacks.onModeration?.("block");
    });

    expect(screen.getByTestId("live-line-moderation")).toHaveTextContent("cut off");
  });

  it("shows a calm inline error on mic-permission denial, never a stack trace", async () => {
    render(<LiveVoicePreview agentId="agent-1" />);
    await userEvent.click(screen.getByTestId("live-talk-button"));
    const session = FakeSession.instances[0];

    act(() => {
      session.callbacks.onStatus?.("error");
      session.callbacks.onError?.(
        "Couldn't access your microphone — check your browser permissions and try again.",
      );
    });

    await waitFor(() =>
      expect(screen.getByTestId("live-error")).toHaveTextContent(
        "Couldn't access your microphone",
      ),
    );
    expect(screen.getByTestId("live-talk-button")).toBeInTheDocument();
  });

  it("Hang up calls session.stop()", async () => {
    render(<LiveVoicePreview agentId="agent-1" />);
    await userEvent.click(screen.getByTestId("live-talk-button"));
    const session = FakeSession.instances[0];
    act(() => {
      session.callbacks.onStatus?.("live");
    });

    await waitFor(() => screen.getByTestId("live-hang-up"));
    await userEvent.click(screen.getByTestId("live-hang-up"));

    expect(session.stopped).toBe(true);
  });
});
