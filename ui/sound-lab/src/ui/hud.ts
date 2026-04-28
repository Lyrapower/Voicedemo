export type HudSnapshot = {
  fps: number;
  /** Rolling avg from telemetry + local frame budget */
  latencyMsAvg: number;
  particleCount: number;
  coherence: number;
};

/**
 * FPS + latency + particle count overlay (acceptance: visible particleCount).
 */
export function createHud(root: HTMLElement): {
  update(s: HudSnapshot): void;
} {
  const el = document.createElement('div');
  el.className = 'hud-lines';
  root.appendChild(el);

  return {
    update(s: HudSnapshot) {
      el.textContent = [
        `fps ${s.fps.toFixed(0)}`,
        `latency ~${s.latencyMsAvg.toFixed(0)} ms`,
        `particles ${s.particleCount}`,
        `coherence ${s.coherence.toFixed(3)}`,
      ].join('\n');
    },
  };
}
