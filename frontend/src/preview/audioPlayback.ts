/**
 * Plays incoming binary agent-audio frames (24 kHz mono PCM s16le — Gemini Live's
 * output rate, distinct from the 16 kHz mic input) back-to-back with no gaps: each
 * pushed frame is scheduled to start exactly when the previous one ends (or
 * immediately, if playback has caught up).
 *
 * `flush()` stops everything currently playing/scheduled WITHOUT closing the context,
 * so barge-in can silence the agent the instant the user starts talking and still play
 * the agent's next turn.
 */
import { AUDIO_OUTPUT_SAMPLE_RATE_HZ } from "./protocol";

export interface PlaybackQueue {
  push(frame: ArrayBuffer): void;
  flush(): void;
  stop(): void;
}

export function createPlaybackQueue(): PlaybackQueue {
  const context = new AudioContext();
  let nextStartTime = context.currentTime;
  const active = new Set<AudioBufferSourceNode>();

  function flush() {
    for (const source of active) {
      try {
        source.stop();
      } catch {
        /* already ended */
      }
    }
    active.clear();
    nextStartTime = context.currentTime;
  }

  return {
    push(frame: ArrayBuffer) {
      const samples = new Int16Array(frame);
      if (!samples.length) return;
      const buffer = context.createBuffer(1, samples.length, AUDIO_OUTPUT_SAMPLE_RATE_HZ);
      const channel = buffer.getChannelData(0);
      for (let i = 0; i < samples.length; i++) channel[i] = samples[i] / 0x8000;

      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(context.destination);
      source.onended = () => active.delete(source);
      const startAt = Math.max(nextStartTime, context.currentTime);
      source.start(startAt);
      active.add(source);
      nextStartTime = startAt + buffer.duration;
    },
    flush,
    stop() {
      flush();
      void context.close();
    },
  };
}
