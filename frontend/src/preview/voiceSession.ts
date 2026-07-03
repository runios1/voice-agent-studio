/**
 * Orchestrates one "talk to your agent" call: opens the WS at the frozen route,
 * bridges mic frames up and agent audio down, and turns the JSON control messages
 * into callbacks a React component (or a test) can render off of. Framework-free
 * and fully dependency-injected (socket/mic/playback) so it's testable without a
 * browser's WebSocket/getUserMedia/AudioContext.
 */
import type { ServerMessage } from "./protocol";
import { voiceWsPath } from "./protocol";
import { startMicCapture, type MicCapture } from "./audioCapture";
import { createPlaybackQueue, type PlaybackQueue } from "./audioPlayback";

const WS_OPEN = 1; // WebSocket.OPEN — hardcoded so this module never touches the
// global WebSocket constructor except via the (overridable) default factory.

export type SessionStatus = "idle" | "connecting" | "live" | "ended" | "error";

export interface VoiceSessionCallbacks {
  onStatus?(status: SessionStatus): void;
  onTranscript?(role: "agent" | "lead", text: string): void;
  onDisclosure?(): void;
  onOutcome?(outcome: string): void;
  onError?(message: string): void;
  onEnded?(outcome?: string): void;
}

/** Minimal surface this module needs from a WebSocket — real sockets and fakes
 * used in tests both satisfy it. */
export interface SocketLike {
  readyState: number;
  binaryType: string;
  send(data: string | ArrayBuffer): void;
  close(): void;
  addEventListener(type: "open" | "close" | "error", cb: () => void): void;
  addEventListener(type: "message", cb: (ev: MessageEvent) => void): void;
}

export interface VoiceSessionDeps {
  createSocket?: (url: string) => SocketLike;
  createMic?: (onFrame: (buf: ArrayBuffer) => void) => Promise<MicCapture>;
  createPlayback?: () => PlaybackQueue;
  wsUrl?: (agentId: string) => string;
}

function defaultWsUrl(agentId: string): string {
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${window.location.host}${voiceWsPath(agentId)}`;
}

export class VoiceSession {
  private ws: SocketLike | null = null;
  private mic: MicCapture | null = null;
  private playback: PlaybackQueue | null = null;
  private status: SessionStatus = "idle";

  constructor(
    private readonly agentId: string,
    private readonly callbacks: VoiceSessionCallbacks,
    private readonly deps: VoiceSessionDeps = {},
  ) {}

  async start(): Promise<void> {
    if (this.status === "connecting" || this.status === "live") return;
    this.setStatus("connecting");

    const createMic = this.deps.createMic ?? startMicCapture;
    try {
      this.mic = await createMic((frame) => {
        if (this.ws && this.ws.readyState === WS_OPEN) this.ws.send(frame);
      });
    } catch {
      this.setStatus("error");
      this.callbacks.onError?.(
        "Couldn't access your microphone — check your browser permissions and try again.",
      );
      return;
    }

    const createSocket =
      this.deps.createSocket ?? ((url: string) => new WebSocket(url) as unknown as SocketLike);
    const wsUrl = this.deps.wsUrl ?? defaultWsUrl;
    const ws = createSocket(wsUrl(this.agentId));
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    this.playback = (this.deps.createPlayback ?? createPlaybackQueue)();

    ws.addEventListener("open", () => {
      ws.send(JSON.stringify({ type: "start" }));
      this.setStatus("live");
    });
    ws.addEventListener("message", (event: MessageEvent) => this.handleMessage(event));
    ws.addEventListener("close", () => this.handleClose());
    // no separate 'error' handling: the 'close' event that follows drives recovery
  }

  /** Hang up: tell the server, stop the mic/playback, close the socket. */
  stop(): void {
    if (this.status === "idle" || this.status === "ended") return;
    if (this.ws && this.ws.readyState === WS_OPEN) {
      this.ws.send(JSON.stringify({ type: "stop" }));
    }
    this.ws?.close();
    this.teardownLocal();
    this.setStatus("ended");
  }

  private handleMessage(event: MessageEvent): void {
    if (typeof event.data === "string") {
      let msg: ServerMessage;
      try {
        msg = JSON.parse(event.data) as ServerMessage;
      } catch {
        return;
      }
      switch (msg.type) {
        case "transcript":
          this.callbacks.onTranscript?.(msg.role, msg.text);
          break;
        case "disclosure":
          this.callbacks.onDisclosure?.();
          break;
        case "outcome":
          this.callbacks.onOutcome?.(msg.outcome);
          break;
        case "error":
          this.callbacks.onError?.(msg.message);
          break;
        case "ended":
          this.teardownLocal();
          this.setStatus("ended");
          this.callbacks.onEnded?.(msg.outcome);
          break;
      }
    } else if (event.data instanceof ArrayBuffer) {
      this.playback?.push(event.data);
    }
  }

  private handleClose(): void {
    if (this.status !== "live" && this.status !== "connecting") return;
    this.teardownLocal();
    this.setStatus("error");
    this.callbacks.onError?.("Lost the connection — try again.");
  }

  private teardownLocal(): void {
    this.mic?.stop();
    this.mic = null;
    this.playback?.stop();
    this.playback = null;
  }

  private setStatus(status: SessionStatus): void {
    this.status = status;
    this.callbacks.onStatus?.(status);
  }
}
