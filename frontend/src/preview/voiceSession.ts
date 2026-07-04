/**
 * Orchestrates one "talk to your agent" call: opens the WS at the frozen route,
 * bridges mic frames up and agent audio down, and turns the JSON control messages
 * into callbacks a React component (or a test) can render off of. Framework-free
 * and fully dependency-injected (socket/mic/playback) so it's testable without a
 * browser's WebSocket/getUserMedia/AudioContext.
 */
import type { ServerMessage } from "./protocol";
import { voiceWsPath } from "./protocol";
import type { Event as DashboardEvent } from "../dashboard/types";
import { startMicCapture, type MicCapture } from "./audioCapture";
import { createPlaybackQueue, type PlaybackQueue } from "./audioPlayback";

const WS_OPEN = 1; // WebSocket.OPEN — hardcoded so this module never touches the
// global WebSocket constructor except via the (overridable) default factory.

// Barge-in: when the mic frame's energy (Int16 RMS) crosses this, treat it as the user
// speaking and mute the agent. Tunable; echo cancellation keeps the agent's own audio
// well below it. Stay muted for the hangover after the last speech frame so a brief
// pause mid-sentence doesn't let the agent talk over the user.
const SPEECH_RMS_THRESHOLD = 2000;
const DUCK_HANGOVER_MS = 600;

export type SessionStatus = "idle" | "connecting" | "live" | "ended" | "error";

export interface VoiceSessionCallbacks {
  onStatus?(status: SessionStatus): void;
  onTranscript?(role: "agent" | "lead", text: string): void;
  onDisclosure?(): void;
  onOutcome?(outcome: string): void;
  onError?(message: string): void;
  onEnded?(outcome?: string): void;
  /** A structured event the server recorded for this call (live preview dashboard). */
  onEvent?(event: DashboardEvent): void;
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

/** Cheap RMS voice-activity check on one 16 kHz Int16 PCM frame. */
function hasSpeech(frame: ArrayBuffer): boolean {
  const samples = new Int16Array(frame);
  if (!samples.length) return false;
  let sumSquares = 0;
  for (let i = 0; i < samples.length; i++) sumSquares += samples[i] * samples[i];
  return Math.sqrt(sumSquares / samples.length) > SPEECH_RMS_THRESHOLD;
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
  // While `Date.now() < duckUntil` the user is (recently) speaking: the agent is muted.
  private duckUntil = 0;

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
        // Barge-in: the user is talking — silence the agent immediately and keep it
        // muted for the hangover window (see handleMessage, which drops agent audio).
        if (hasSpeech(frame)) {
          this.duckUntil = Date.now() + DUCK_HANGOVER_MS;
          this.playback?.flush();
        }
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
        case "event":
          this.callbacks.onEvent?.(msg.event);
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
      // Barge-in: while the user is (recently) speaking, drop agent audio so a muted
      // agent doesn't resume from buffered frames.
      if (Date.now() < this.duckUntil) return;
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
