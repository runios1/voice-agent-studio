import { describe, expect, it, vi } from "vitest";
import { VoiceSession, type SocketLike } from "./voiceSession";
import type { MicCapture } from "./audioCapture";
import type { PlaybackQueue } from "./audioPlayback";

/** A fake WebSocket good enough to drive VoiceSession's protocol logic without a
 * browser: readyState + send/close tracking, and manual open/message/close. */
class FakeSocket implements SocketLike {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 3;

  readyState = FakeSocket.CONNECTING;
  binaryType = "blob";
  sent: Array<string | ArrayBuffer> = [];
  closed = false;
  private openCbs: Array<() => void> = [];
  private messageCbs: Array<(ev: MessageEvent) => void> = [];
  private closeCbs: Array<() => void> = [];

  addEventListener(type: "open" | "close" | "error", cb: () => void): void;
  addEventListener(type: "message", cb: (ev: MessageEvent) => void): void;
  addEventListener(type: string, cb: any): void {
    if (type === "open") this.openCbs.push(cb);
    else if (type === "message") this.messageCbs.push(cb);
    else if (type === "close") this.closeCbs.push(cb);
  }

  send(data: string | ArrayBuffer): void {
    this.sent.push(data);
  }

  close(): void {
    this.closed = true;
    this.readyState = FakeSocket.CLOSED;
  }

  simulateOpen(): void {
    this.readyState = FakeSocket.OPEN;
    this.openCbs.forEach((cb) => cb());
  }

  simulateMessage(data: unknown): void {
    this.messageCbs.forEach((cb) => cb({ data } as MessageEvent));
  }

  simulateClose(): void {
    this.readyState = FakeSocket.CLOSED;
    this.closeCbs.forEach((cb) => cb());
  }
}

function setup() {
  const socket = new FakeSocket();
  const pushed: ArrayBuffer[] = [];
  let playbackStopped = false;
  const playback: PlaybackQueue = {
    push: (buf) => pushed.push(buf),
    flush: () => {},
    stop: () => { playbackStopped = true; },
  };
  let micStopped = false;
  let capturedOnFrame: ((buf: ArrayBuffer) => void) | null = null;
  const createMic = vi.fn(async (onFrame: (buf: ArrayBuffer) => void) => {
    capturedOnFrame = onFrame;
    const mic: MicCapture = { stop: () => { micStopped = true; } };
    return mic;
  });
  const createSocket = vi.fn(() => socket as SocketLike);
  const createPlayback = vi.fn(() => playback);

  const callbacks = {
    onStatus: vi.fn(),
    onTranscript: vi.fn(),
    onDisclosure: vi.fn(),
    onOutcome: vi.fn(),
    onError: vi.fn(),
    onEnded: vi.fn(),
  };

  const session = new VoiceSession("agent-1", callbacks, {
    createSocket,
    createMic,
    createPlayback,
    wsUrl: (id) => `ws://test/${id}`,
  });

  return {
    session,
    socket,
    callbacks,
    pushed,
    createSocket,
    getMicStopped: () => micStopped,
    getPlaybackStopped: () => playbackStopped,
    sendMicFrame: (buf: ArrayBuffer) => capturedOnFrame?.(buf),
  };
}

describe("VoiceSession", () => {
  it("acquires the mic, opens the socket at the frozen route, and sends 'start' on open", async () => {
    const { session, socket, callbacks, createSocket } = setup();
    await session.start();

    expect(createSocket).toHaveBeenCalledWith("ws://test/agent-1");
    expect(callbacks.onStatus).toHaveBeenCalledWith("connecting");

    socket.simulateOpen();
    expect(socket.sent).toEqual([JSON.stringify({ type: "start" })]);
    expect(callbacks.onStatus).toHaveBeenCalledWith("live");
  });

  it("forwards mic frames as binary sends only once the socket is open", async () => {
    const { session, socket, sendMicFrame } = setup();
    await session.start();
    const frame = new ArrayBuffer(4);

    sendMicFrame(frame);
    expect(socket.sent).toEqual([]); // not open yet — dropped, not queued

    socket.simulateOpen();
    sendMicFrame(frame);
    expect(socket.sent).toEqual([JSON.stringify({ type: "start" }), frame]);
  });

  it("dispatches transcript, disclosure, outcome, and error JSON messages", async () => {
    const { session, socket, callbacks } = setup();
    await session.start();
    socket.simulateOpen();

    socket.simulateMessage(JSON.stringify({ type: "transcript", role: "agent", text: "Hi" }));
    expect(callbacks.onTranscript).toHaveBeenCalledWith("agent", "Hi");

    socket.simulateMessage(JSON.stringify({ type: "disclosure" }));
    expect(callbacks.onDisclosure).toHaveBeenCalled();

    socket.simulateMessage(JSON.stringify({ type: "outcome", outcome: "booked" }));
    expect(callbacks.onOutcome).toHaveBeenCalledWith("booked");

    socket.simulateMessage(JSON.stringify({ type: "error", message: "oops" }));
    expect(callbacks.onError).toHaveBeenCalledWith("oops");
  });

  it("pushes binary frames to the playback queue", async () => {
    const { session, socket, pushed } = setup();
    await session.start();
    socket.simulateOpen();

    const agentAudio = new ArrayBuffer(8);
    socket.simulateMessage(agentAudio);
    expect(pushed).toEqual([agentAudio]);
  });

  it("on 'ended', tears down mic + playback and reports the outcome without an error", async () => {
    const { session, socket, callbacks, getMicStopped, getPlaybackStopped } = setup();
    await session.start();
    socket.simulateOpen();

    socket.simulateMessage(JSON.stringify({ type: "ended", outcome: "qualified" }));

    expect(callbacks.onEnded).toHaveBeenCalledWith("qualified");
    expect(callbacks.onStatus).toHaveBeenCalledWith("ended");
    expect(callbacks.onError).not.toHaveBeenCalled();
    expect(getMicStopped()).toBe(true);
    expect(getPlaybackStopped()).toBe(true);
  });

  it("surfaces mic-permission denial as a calm error, never opening a socket", async () => {
    const callbacks = {
      onStatus: vi.fn(),
      onTranscript: vi.fn(),
      onDisclosure: vi.fn(),
      onOutcome: vi.fn(),
      onError: vi.fn(),
      onEnded: vi.fn(),
    };
    const createSocket = vi.fn();
    const session = new VoiceSession("agent-1", callbacks, {
      createMic: async () => {
        throw new Error("permission denied");
      },
      createSocket,
    });

    await session.start();

    expect(createSocket).not.toHaveBeenCalled();
    expect(callbacks.onStatus).toHaveBeenCalledWith("error");
    expect(callbacks.onError).toHaveBeenCalledWith(expect.stringMatching(/microphone/i));
  });

  it("on an unexpected close while live, tears down and reports a connection error", async () => {
    const { session, socket, callbacks, getMicStopped } = setup();
    await session.start();
    socket.simulateOpen();

    socket.simulateClose();

    expect(callbacks.onStatus).toHaveBeenCalledWith("error");
    expect(callbacks.onError).toHaveBeenCalledWith(expect.stringMatching(/connection/i));
    expect(getMicStopped()).toBe(true);
  });

  it("stop() sends 'stop', closes the socket, and tears down local resources", async () => {
    const { session, socket, callbacks, getMicStopped, getPlaybackStopped } = setup();
    await session.start();
    socket.simulateOpen();

    session.stop();

    expect(socket.sent).toContain(JSON.stringify({ type: "stop" }));
    expect(socket.closed).toBe(true);
    expect(getMicStopped()).toBe(true);
    expect(getPlaybackStopped()).toBe(true);
    expect(callbacks.onStatus).toHaveBeenCalledWith("ended");
  });
});
