export type SpectrumSample = {
  bins: Float32Array;
  amp: number;
  freq: number;
};

/**
 * Shared analyser for microphone or demo music.
 * Public API required by task: getSpectrum().
 */
export class AudioAnalyser {
  private ctx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private stream: MediaStream | null = null;
  private mediaSource: MediaElementAudioSourceNode | null = null;
  private bins = new Float32Array(1024);
  private fftSize = 2048;

  private ensureContext(): AudioContext {
    if (!this.ctx) this.ctx = new AudioContext();
    if (!this.analyser) {
      this.analyser = this.ctx.createAnalyser();
      this.analyser.fftSize = this.fftSize;
      this.analyser.smoothingTimeConstant = 0.75;
      this.bins = new Float32Array(this.analyser.frequencyBinCount);
    }
    return this.ctx;
  }

  async useMicrophone(): Promise<void> {
    const ctx = this.ensureContext();
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
      video: false,
    });
    const src = ctx.createMediaStreamSource(this.stream);
    src.connect(this.analyser!);
  }

  async useMediaElement(el: HTMLMediaElement): Promise<void> {
    const ctx = this.ensureContext();
    if (!this.mediaSource) {
      this.mediaSource = ctx.createMediaElementSource(el);
      this.mediaSource.connect(this.analyser!);
      this.mediaSource.connect(ctx.destination);
    }
    if (ctx.state === 'suspended') await ctx.resume();
  }

  getSpectrum(): SpectrumSample {
    if (!this.analyser || !this.ctx) {
      return { bins: this.bins, amp: 0, freq: 0 };
    }
    this.analyser.getFloatFrequencyData(this.bins);
    let maxDb = -140;
    let maxI = 0;
    let energy = 0;
    for (let i = 1; i < this.bins.length; i++) {
      const db = this.bins[i] ?? -140;
      if (db > maxDb) {
        maxDb = db;
        maxI = i;
      }
      energy += Math.max(-120, db) + 120;
    }
    const nyq = this.ctx.sampleRate / 2;
    const freq = (maxI / Math.max(1, this.bins.length - 1)) * nyq;
    const amp = Math.min(1, energy / (this.bins.length * 120));
    return { bins: this.bins, amp, freq };
  }

  stop(): void {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
  }
}

