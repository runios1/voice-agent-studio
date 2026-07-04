/**
 * DEV-ONLY scripted demo of the side-by-side live preview dashboard. Mounts the real
 * <LiveVoicePreview/> with a scripted socket double (no backend, no mic, no Gemini) that
 * replays a booking call — transcript + the forwarded `event` frames — so the left
 * conversation and the right "In your dashboard" mirror both animate. Not part of the
 * app or the build; served only under `vite` at /preview-demo.html for screenshots/GIFs.
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../index.css";
import { LiveVoicePreview } from "./LiveVoicePreview";
import type { LiveVoiceSessionDeps, SocketLike } from "./liveVoiceSession";

const SLOT_START = "2026-08-06T15:00:00Z";

let seq = 0;
function ev(type: string, payload: Record<string, unknown> = {}) {
  return {
    type: "event",
    event: {
      event_id: `e-${++seq}`,
      type,
      occurred_at: new Date().toISOString(),
      severity: "info",
      tenant_id: "preview",
      campaign_id: "preview",
      lead_id: null,
      call_id: "call-demo",
      agent_id: "demo",
      payload,
    },
  };
}

/** [delayMs, frame] timeline of a booking call, mixing UI frames + forwarded events. */
const SCRIPT: [number, Record<string, unknown>][] = [
  [300, ev("call.started", {})],
  [700, { type: "transcript", role: "agent", text: "Hi! Quick heads-up — I'm an AI assistant calling on behalf of Acme." }],
  [900, { type: "disclosure" }],
  [950, ev("disclosure.spoken", { text: "I'm an AI assistant calling on behalf of Acme." })],
  [2300, { type: "transcript", role: "lead", text: "Oh, okay — what's this about?" }],
  [3400, { type: "transcript", role: "agent", text: "We help RevOps teams cut onboarding time. Do you handle that at your company?" }],
  [4600, { type: "transcript", role: "lead", text: "Yeah, that's me. We've been struggling with it actually." }],
  [5200, { type: "tool", name: "calendar", timing: "in_call" }],
  [5250, ev("tool.invoked", { tool_name: "calendar", params: { start_iso: SLOT_START } })],
  [5300, ev("slot.booked", { slot_start: SLOT_START, calendar_id: "sales@acme.com" })],
  [6100, { type: "transcript", role: "agent", text: "Perfect — I've got you down for Thursday at 3pm. I'll send a confirmation." }],
  [6600, { type: "tool", name: "email", timing: "post_call" }],
  [6650, ev("tool.invoked", { tool_name: "email", params: { to: "jordan@northwind.io" } })],
  [7200, ev("lead.outcome", { outcome: "qualified" })],
  [7300, ev("call.ended", { ended_reason: "booked" })],
  [7350, { type: "outcome", outcome: "booked" }],
  [7600, { type: "ended", outcome: "booked" }],
];

class ScriptedSocket {
  readyState = 1;
  binaryType = "arraybuffer";
  private listeners: Record<string, ((ev?: unknown) => void)[]> = {};
  constructor() {
    setTimeout(() => this.fire("open"), 30);
  }
  send(data: string | ArrayBuffer): void {
    if (typeof data !== "string") return;
    if (JSON.parse(data).type !== "start") return;
    for (const [delay, frame] of SCRIPT) {
      setTimeout(() => {
        this.listeners["message"]?.forEach((cb) =>
          cb({ data: JSON.stringify(frame) } as MessageEvent),
        );
      }, delay);
    }
  }
  close(): void {
    this.readyState = 3;
  }
  addEventListener(type: string, cb: (ev?: unknown) => void): void {
    (this.listeners[type] ??= []).push(cb);
  }
  private fire(type: string) {
    this.listeners[type]?.forEach((cb) => cb());
  }
}

const deps: LiveVoiceSessionDeps = {
  createSocket: () => new ScriptedSocket() as unknown as SocketLike,
  createMic: async () => ({ stop() {} }),
  createPlayback: () => ({ push() {}, flush() {}, stop() {} }),
  wsUrl: () => "ws://demo",
};

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <div style={{ height: "100vh" }}>
      <LiveVoicePreview agentId="demo" deps={deps} />
    </div>
  </StrictMode>,
);
