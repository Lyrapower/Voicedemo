/**
 * Web Audio mic path + AnalyserNode FFT (2048) for voice frequency / level.
 */
export class MicAudio {
  private ctx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private freq: Float32Array;
  private time: Float32Array;
  private stream: MediaStream | null = null;

  readonly fftSize = 2048 as const;

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
      video: false,
    });
    this.ctx = new AudioContext();
    const src = this.ctx.createMediaStreamSource(this.stream);
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = this.fftSize;
    this.analyser.smoothingTimeConstant = 0.72;
    src.connect(this.analyser);
    this.freq = new Float32Array(this.analyser.frequencyBinCount);
    this.time = new Float32Array(this.analyser.fftSize);
  }

  /** Peak bin → Hz (client estimate). */
  getVoiceFreqHz(): number {
    if (!this.analyser || !this.ctx) return 0;
    this.analyser.getFloatFrequencyData(this.freq);
    let bestI = 0;
    let best = -Infinity;
    for (let i = 2; i < this.freq.length; i++) {
      const v = this.freq[i] ?? -Infinity;
      if (v > best) {
        best = v;
        bestI = i;
      }
    }
    const nyquist = this.ctx.sampleRate / 2;
    return (bestI / Math.max(1, this.freq.length)) * nyquist;
  }

  /** Rough RMS 0..1 from time domain. */
  getRms(): number {
    if (!this.analyser) return 0;
    this.analyser.getFloatTimeDomainData(this.time);
    let s = 0;
    for (let i = 0; i < this.time.length; i++) {
      const x = this.time[i] ?? 0;
      s += x * x;
    }
    return Math.min(1, Math.sqrt(s / this.time.length) * 3.2);
  }

  isRunning(): boolean {
    return this.analyser !== null;
  }

  stop(): void {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    void this.ctx?.close();
    this.ctx = null;
    this.analyser = null;
  }
}
