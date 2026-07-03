/**
 * Wire protocol for the Live-native preview (P4-4). The audio format and route are
 * UNCHANGED from `contracts/voice_preview` (re-exported here, not redefined) — Live
 * hears/speaks the same 16 kHz-in/24 kHz-out PCM at the same WS route, only the
 * engine behind it changed. `ToolMessage` / `ModerationMessage` /
 * `CutPlaybackMessage` are an ADDITIVE extension documented in
 * `docs/contract-change-requests/p4-4-live-preview-events.md` rather than a silent
 * edit to the frozen `contracts/voice_preview/protocol.py` — do not invent further
 * message shapes without a matching CCR update.
 */
export {
  AUDIO_SAMPLE_RATE_HZ,
  AUDIO_OUTPUT_SAMPLE_RATE_HZ,
  AUDIO_CHANNELS,
  AUDIO_SAMPLE_FORMAT,
  voiceWsPath,
} from "./protocol";
export type {
  StartMessage,
  StopMessage,
  TranscriptMessage,
  DisclosureMessage,
  OutcomeMessage,
  ErrorMessage,
  EndedMessage,
} from "./protocol";

import type {
  TranscriptMessage,
  DisclosureMessage,
  OutcomeMessage,
  ErrorMessage,
  EndedMessage,
} from "./protocol";

// --- new for Phase 4 (server -> client only) ------------------------------------ //
export interface ToolMessage {
  type: "tool";
  name: string;
  timing: "in_call" | "post_call";
}

export interface ModerationMessage {
  type: "moderation";
  verdict: "flag" | "block";
}

/** A dedicated signal for `AudioTransport.cut_playback()` — distinct from any
 * `moderation` display event the session also sends via `send_event`. The client's
 * only correct response is to flush whatever agent audio is already scheduled. */
export interface CutPlaybackMessage {
  type: "cut_playback";
}

export type LiveServerMessage =
  | TranscriptMessage
  | DisclosureMessage
  | OutcomeMessage
  | ErrorMessage
  | EndedMessage
  | ToolMessage
  | ModerationMessage
  | CutPlaybackMessage;
