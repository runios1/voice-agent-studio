/**
 * Mic capture -> 16 kHz mono PCM s16le, framed as ArrayBuffers ready to send as
 * binary WS frames (contracts/voice_preview). Downsampling runs inside an
 * AudioWorklet (off the main thread) via a Blob-URL module, so no extra static
 * asset/build wiring is needed for the one processor this needs.
 *
 * Plain integer decimation (no anti-alias filter) — sufficient for speech-quality
 * preview audio without pulling in a resampling library.
 */
import { AUDIO_SAMPLE_RATE_HZ } from "./protocol";

const WORKLET_NAME = "vas-pcm-downsampler";

const WORKLET_SOURCE = `
class PcmDownsampler extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this._ratio = sampleRate / (options.processorOptions?.targetRate ?? ${AUDIO_SAMPLE_RATE_HZ});
    this._acc = 0;
  }
  process(inputs) {
    const channel = inputs[0]?.[0];
    if (channel && channel.length) {
      const kept = [];
      for (let i = 0; i < channel.length; i++) {
        this._acc += 1;
        if (this._acc >= this._ratio) {
          this._acc -= this._ratio;
          kept.push(channel[i]);
        }
      }
      if (kept.length) {
        const pcm = new Int16Array(kept.length);
        for (let i = 0; i < kept.length; i++) {
          const s = Math.max(-1, Math.min(1, kept[i]));
          pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
        this.port.postMessage(pcm.buffer, [pcm.buffer]);
      }
    }
    return true;
  }
}
registerProcessor("${WORKLET_NAME}", PcmDownsampler);
`;

export interface MicCapture {
  stop(): void;
}

export async function startMicCapture(
  onFrame: (frame: ArrayBuffer) => void,
): Promise<MicCapture> {
  // Force echo cancellation + noise suppression: without them the mic picks up the
  // agent's own audio from the speakers and STT transcribes it as if the user said
  // it, so the agent ends up talking to itself. (Headphones also solve this.)
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  });
  const context = new AudioContext();
  const blobUrl = URL.createObjectURL(
    new Blob([WORKLET_SOURCE], { type: "application/javascript" }),
  );
  try {
    await context.audioWorklet.addModule(blobUrl);
  } finally {
    URL.revokeObjectURL(blobUrl);
  }

  const source = context.createMediaStreamSource(stream);
  const worklet = new AudioWorkletNode(context, WORKLET_NAME, {
    processorOptions: { targetRate: AUDIO_SAMPLE_RATE_HZ },
  });
  worklet.port.onmessage = (event) => onFrame(event.data as ArrayBuffer);
  source.connect(worklet);

  return {
    stop() {
      worklet.port.onmessage = null;
      source.disconnect();
      worklet.disconnect();
      stream.getTracks().forEach((track) => track.stop());
      void context.close();
    },
  };
}
