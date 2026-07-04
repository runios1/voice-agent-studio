/**
 * TypeScript mirror of the FROZEN contract `contracts/voice_preview/protocol.py`.
 * READ-ONLY reflection — do not invent message types or fields; a shape that's
 * wrong for this work is a docs/contract-change-requests/ entry, not a silent
 * divergence.
 */

import type { Event as DashboardEvent } from "../dashboard/types";

export const AUDIO_SAMPLE_RATE_HZ = 16_000; // INPUT: lead mic -> server (Gemini Live wants 16 kHz)
export const AUDIO_OUTPUT_SAMPLE_RATE_HZ = 24_000; // OUTPUT: agent audio <- server (Gemini Live emits 24 kHz)
export const AUDIO_CHANNELS = 1;
export const AUDIO_SAMPLE_FORMAT = "pcm_s16le";
export const WS_ROUTE_TEMPLATE = "/api/agents/{agent_id}/preview/voice";

// --- client -> server (JSON control; binary frames are lead-mic audio, no envelope) -------- //
export interface StartMessage {
  type: "start";
}

export interface StopMessage {
  type: "stop";
}

// --- server -> client (JSON events; binary frames are agent audio) ------------------------- //
export interface TranscriptMessage {
  type: "transcript";
  role: "agent" | "lead";
  text: string;
}

export interface DisclosureMessage {
  type: "disclosure";
}

export interface OutcomeMessage {
  type: "outcome";
  outcome: string;
}

export interface ErrorMessage {
  type: "error";
  message: string;
}

export interface EndedMessage {
  type: "ended";
  outcome?: string;
}

/** ADDITIVE wire extension (live preview dashboard): the server mirrors every
 *  structured event it records for THIS call to the browser, in the exact shape the
 *  ops dashboard consumes off its SSE stream — so the preview can render a
 *  dashboard-identical live view of the call. Backed by `_ForwardingSink`
 *  (backend/live_agent/preview_transport.py). */
export interface EventMessage {
  type: "event";
  event: DashboardEvent;
}

export type ServerMessage =
  | TranscriptMessage
  | DisclosureMessage
  | OutcomeMessage
  | ErrorMessage
  | EndedMessage
  | EventMessage;

export function voiceWsPath(agentId: string): string {
  return WS_ROUTE_TEMPLATE.replace("{agent_id}", encodeURIComponent(agentId));
}
