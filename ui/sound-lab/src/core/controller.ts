/**
 * OPTION_A_SIMPLE: coherence = 1 − |voiceFreq − aiFreq| / maxFreq (clamped).
 * Phase-2 may switch to dot-product on spectra (see spec).
 */
export const MAX_FREQ_HZ = 8000;

export type TelemetrySample = {
  t: number;
  voiceFreq: number;
  aiFreq: number;
  aiAmplitude: number;
  latencyMs: number;
};

export function coherenceSimple(voiceHz: number, aiHz: number, maxFreq = MAX_FREQ_HZ): number {
  const v = Math.max(0, voiceHz);
  const a = Math.max(0, aiHz);
  const diff = Math.abs(v - a);
  return Math.max(0, Math.min(1, 1 - diff / maxFreq));
}

export type ParticleDrive = {
  coherence: number;
  /** 0..1 blend for visuals */
  energy: number;
  /** Audio analyser amplitude (0..1) -> renderer uAmp */
  amp: number;
  /** Dominant analyser frequency (Hz) -> renderer uFreq */
  freq: number;
  voiceHz: number;
  aiHz: number;
  aiAmplitude: number;
};

/**
 * When mic is active, prefer FFT `voiceHzMic`; else telemetry `voiceFreq`.
 */
export function computeParticleDrive(
  tel: TelemetrySample,
  voiceHzMic: number,
  micActive: boolean,
  analyserAmp: number,
  analyserFreq: number,
): ParticleDrive {
  const voiceHz = micActive && voiceHzMic > 30 ? voiceHzMic : Math.max(0, tel.voiceFreq);
  const coh = coherenceSimple(voiceHz, tel.aiFreq);
  const energy = Math.min(1, coh * 0.55 + tel.aiAmplitude * 0.35 + analyserAmp * 0.45);
  return {
    coherence: coh,
    energy,
    amp: analyserAmp,
    freq: analyserFreq > 10 ? analyserFreq : voiceHz,
    voiceHz,
    aiHz: tel.aiFreq,
    aiAmplitude: tel.aiAmplitude,
  };
}
