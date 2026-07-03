/**
 * Orchestrates one Live-native preview call (P4-4): opens the WS, bridges mic
 * frames up and agent audio down, and turns the JSON control messages (the
 * unchanged Phase-3 set plus the additive `tool`/`moderation`/`cut_playback`
 * events, see `livePreviewProtocol.ts`) into callbacks a React component (or a
 * test) can render off of. Framework-free and fully dependency-injected
 * (socket/mic/playback), same posture as `voiceSession.ts`.
 *
 * There is no server-sent "who's talking now" event — Live's turn-taking is
 * internal to the model — so the speaking/listening indicator is inferred
 * client-side: "agent" while agent audio frames are actively arriving (with a
 * short decay so brief inter-word gaps don't flicker), "listening" otherwise or
 * the instant the user's own mic crosses the speech threshold (which also drives
 * barge-in muting, unchanged from Phase 3).
 */
import type { LiveServerMessage } from "./livePreviewProtocol";
import { voiceWsPath } from "./livePreviewProtocol";
import { startMicCapture, type MicCapture } from "./audioCapture";
import { createPlaybackQueue, type PlaybackQueue } from "./audioPlayback";

const WS_OPEN = 1; // WebSocket.OPEN

const SPEECH_RMS_THRESHOLD = 2000;
const DUCK_HANGOVER_MS = 600;
const AGENT_SPEAKING_DECAY_MS = 300;

export type SessionStatus = "idle" | "connecting" | "live" | "ended" | "error";
export type SpeakingIndicator = "agent" | "listening";

export interface LiveVoiceSessionCallbacks {
  onStatus?(status: SessionStatus): void;
  onTranscript?(role: "agent" | "lead", text: string): void;
  onDisclosure?(): void;
  onTool?(name: string, timing: "in_call" | "post_call"): void;
  onModeration?(verdict: "flag" | "block"): void;
  onOutcome?(outcome: string): void;
  onError?(message: string): void;
  onEnded?(outcome?: string): void;
  onIndicator?(state: SpeakingIndicator): void;
}

export interface SocketLike {
  readyState: number;
  binaryType: string;
  send(data: string | ArrayBuffer): void;
  close(): void;
  addEventListener(type: "open" | "close" | "error", cb: () => void): void;
  addEventListener(type: "message", cb: (ev: MessageEvent) => void): void;
}

export interface LiveVoiceSessionDeps {
  createSocket?: (url: string) => SocketLike;
  createMic?: (onFrame: (buf: ArrayBuffer) => void) => Promise<MicCapture>;
  createPlayback?: () => PlaybackQueue;
  wsUrl?: (agentId: string) => string;
}

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

export class LiveVoiceSession {
  private ws: SocketLike | null = null;
  private mic: MicCapture | null = null;
  private playback: PlaybackQueue | null = null;
  private status: SessionStatus = "idle";
  private duckUntil = 0;
  private indicator: SpeakingIndicator = "listening";
  private agentAudioGen = 0;

  constructor(
    private readonly agentId: string,
    private readonly callbacks: LiveVoiceSessionCallbacks,
    private readonly deps: LiveVoiceSessionDeps = {},
  ) {}

  async start(): Promise<void> {
    if (this.status === "connecting" || this.status === "live") return;
    this.setStatus("connecting");

    const createMic = this.deps.createMic ?? startMicCapture;
    try {
      this.mic = await createMic((frame) => {
        if (this.ws && this.ws.readyState === WS_OPEN) this.ws.send(frame);
        if (hasSpeech(frame)) {
          this.duckUntil = Date.now() + DUCK_HANGOVER_MS;
          this.playback?.flush();
          this.setIndicator("listening");
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
  }

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
      let msg: LiveServerMessage;
      try {
        msg = JSON.parse(event.data) as LiveServerMessage;
      } catch {
        return;
      }
      switch (msg.type) {
        case "transcript":
          if (msg.role === "lead") this.setIndicator("listening");
          this.callbacks.onTranscript?.(msg.role, msg.text);
          break;
        case "disclosure":
          this.callbacks.onDisclosure?.();
          break;
        case "tool":
          this.callbacks.onTool?.(msg.name, msg.timing);
          break;
        case "moderation":
          if (msg.verdict === "block") {
            this.playback?.flush();
            this.setIndicator("listening");
          }
          this.callbacks.onModeration?.(msg.verdict);
          break;
        case "cut_playback":
          this.playback?.flush();
          this.setIndicator("listening");
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
      if (Date.now() < this.duckUntil) return;
      this.playback?.push(event.data);
      this.markAgentSpeaking();
    }
  }

  /** Agent audio is arriving now: show "agent speaking" and schedule a decay back
   * to "listening" unless a newer frame supersedes this one first. */
  private markAgentSpeaking(): void {
    this.setIndicator("agent");
    const gen = ++this.agentAudioGen;
    setTimeout(() => {
      if (gen === this.agentAudioGen) this.setIndicator("listening");
    }, AGENT_SPEAKING_DECAY_MS);
  }

  private setIndicator(state: SpeakingIndicator): void {
    if (this.indicator === state) return;
    this.indicator = state;
    this.callbacks.onIndicator?.(state);
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
