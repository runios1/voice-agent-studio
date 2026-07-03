/**
 * TypeScript mirror of the FROZEN contract `contracts/voice_preview/protocol.py`.
 * READ-ONLY reflection — do not invent message types or fields; a shape that's
 * wrong for this work is a docs/contract-change-requests/ entry, not a silent
 * divergence.
 */

export const AUDIO_SAMPLE_RATE_HZ = 16_000;
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

export type ServerMessage =
  | TranscriptMessage
  | DisclosureMessage
  | OutcomeMessage
  | ErrorMessage
  | EndedMessage;

export function voiceWsPath(agentId: string): string {
  return WS_ROUTE_TEMPLATE.replace("{agent_id}", encodeURIComponent(agentId));
}
