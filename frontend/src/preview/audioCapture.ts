/**
 * Mic capture -> 16 kHz mono PCM s16le, framed as ArrayBuffers ready to send as
 * binary WS frames (contracts/voice_preview). Downsampling runs inside an
 * AudioWorklet (off the main thread) via a Blob-URL module, so no extra static
 * asset/build wiring is needed for the one processor this needs.
 *
 * IMPORTANT: this must resample properly, not just drop samples. Plain integer
 * decimation aliases speech badly enough that Gemini Live's ASR can't transcribe it
 * (the agent's VAD still fires on the energy, so it pauses — but never "hears" a
 * word, so it never replies). We use box-filter averaging: each output sample is the
 * mean of the input samples in its window, which low-passes as it decimates and
 * handles a fractional source:target ratio (e.g. 48000:16000 = 3, 44100:16000 ≈ 2.76).
 * Validated end-to-end against the live model — averaged audio transcribes; decimated
 * audio does not.
 */
import { AUDIO_SAMPLE_RATE_HZ } from "./protocol";

const WORKLET_NAME = "vas-pcm-downsampler";

const WORKLET_SOURCE = `
class PcmDownsampler extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this._ratio = sampleRate / (options.processorOptions?.targetRate ?? ${AUDIO_SAMPLE_RATE_HZ});
    this._sum = 0;      // running sum of the current output window
    this._count = 0;    // input samples accumulated into it
    this._need = this._ratio; // input samples still owed before we emit one output sample
  }
  process(inputs) {
    const channel = inputs[0]?.[0];
    if (channel && channel.length) {
      const kept = [];
      for (let i = 0; i < channel.length; i++) {
        this._sum += channel[i];
        this._count += 1;
        this._need -= 1;
        if (this._need <= 0) {
          const avg = this._count ? this._sum / this._count : 0;
          const s = Math.max(-1, Math.min(1, avg));
          kept.push(s < 0 ? s * 0x8000 : s * 0x7fff);
          this._sum = 0;
          this._count = 0;
          this._need += this._ratio; // carry the fraction so the rate stays exact
        }
      }
      if (kept.length) {
        const pcm = Int16Array.from(kept);
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
  // Autoplay policy can leave a freshly-created AudioContext "suspended", in which case
  // the mic graph produces silent/near-empty frames even though it looks connected.
  // Resume it (we're inside the Talk-button user gesture, so this is allowed).
  if (context.state === "suspended") {
    try {
      await context.resume();
    } catch {
      /* best effort — the meter below will reveal a silent mic either way */
    }
  }
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
  // Dev meter: prove whether the mic is actually capturing sound. Logs the loudest
  // frame roughly once a second — if this stays near 0 while you talk, the mic itself
  // is silent (device/permission/context), not anything downstream.
  let meterPeak = 0;
  let meterAt = (typeof performance !== "undefined" ? performance.now() : Date.now());
  worklet.port.onmessage = (event) => {
    const buf = event.data as ArrayBuffer;
    const samples = new Int16Array(buf);
    for (let i = 0; i < samples.length; i++) {
      const a = Math.abs(samples[i]);
      if (a > meterPeak) meterPeak = a;
    }
    const now = typeof performance !== "undefined" ? performance.now() : Date.now();
    if (now - meterAt >= 1000) {
      // eslint-disable-next-line no-console
      console.log(`[mic] peak amplitude ${meterPeak}/32767 (${((meterPeak / 32767) * 100) | 0}%)`);
      meterPeak = 0;
      meterAt = now;
    }
    onFrame(buf);
  };
  source.connect(worklet);
  // Some engines only pull an AudioWorkletNode once it reaches a sink; give it one that
  // outputs nothing so process() runs reliably even though we don't want to hear the mic.
  const sink = context.createGain();
  sink.gain.value = 0;
  worklet.connect(sink).connect(context.destination);

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
