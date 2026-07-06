/** 视觉宪法:改这里 = 改全场。数值语义见 issues/v1.1-visual-debt.md */
export const TOKENS = {
  particles: { desktop: 62000, mobile: 28000 },
  breath: { period: 12.5, amp: 0.05 },
  thinking: { scale: 0.52, swirl: 1.4 },
  ripple: { speed: 9.0, width: 1.2, life: 2.2 },
  spark: { ratio: 0.97, freq: 14.0 },
  camera: { z: 26, y: 1.5, fov: 46 },
  color: {
    coldEdge: [0.46, 0.36, 0.72], coldCore: [0.72, 0.66, 0.92],
    warmEdge: [0.78, 0.62, 0.90], warmCore: [0.96, 0.90, 0.78],
  },
} as const;
