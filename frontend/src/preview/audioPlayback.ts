/**
 * Plays incoming binary agent-audio frames (16 kHz mono PCM s16le) back-to-back
 * with no gaps: each pushed frame is scheduled to start exactly when the previous
 * one ends (or immediately, if playback has caught up).
 */
import { AUDIO_SAMPLE_RATE_HZ } from "./protocol";

export interface PlaybackQueue {
  push(frame: ArrayBuffer): void;
  stop(): void;
}

export function createPlaybackQueue(): PlaybackQueue {
  const context = new AudioContext();
  let nextStartTime = context.currentTime;

  return {
    push(frame: ArrayBuffer) {
      const samples = new Int16Array(frame);
      if (!samples.length) return;
      const buffer = context.createBuffer(1, samples.length, AUDIO_SAMPLE_RATE_HZ);
      const channel = buffer.getChannelData(0);
      for (let i = 0; i < samples.length; i++) channel[i] = samples[i] / 0x8000;

      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(context.destination);
      const startAt = Math.max(nextStartTime, context.currentTime);
      source.start(startAt);
      nextStartTime = startAt + buffer.duration;
    },
    stop() {
      nextStartTime = context.currentTime;
      void context.close();
    },
  };
}
