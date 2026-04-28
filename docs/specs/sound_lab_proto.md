# Sound Lab (internal) · Garden (user-facing) — live particle audio UI

**Status:** Phase-1 prototype spec  
**Last updated:** 2026-04-27

---

## 1 · Overview

| | |
|--|--|
| **User-facing name** | Garden |
| **Internal repo dir / code refs** | `sound-lab` (`ui/sound-lab/`) |
| **Goal** | Show mic voice + AI telemetry (`aiFreq`, `aiAmplitude` / `aiAmp`) as a 3-D particle flow driven by coherence and audio energy. |

---

## 2 · Tech stack

- **three.js** r165 (vanilla TypeScript, no React)
- **lil-gui** (parameter sliders)
- **Vite** + **pnpm** (package manager and dev/build)

---

## 3 · Data packet (telemetry)

**Endpoint (FastAPI stub):** `http://127.0.0.1:8787/api/telemetry`  
**Method:** `GET`  
**Shape (JSON):**

```json
{
  "t": 0,
  "voiceFreq": 0,
  "aiFreq": 0,
  "aiAmplitude": 0,
  "latencyMs": 0
}
```

- `voiceFreq` may be overridden or blended with client-side FFT estimate when the mic is active; server mock may emit a sine-wave style trajectory until fully wired.
- `latencyMs` is end-to-end telemetry hint for HUD (avg target ≤60 ms in acceptance).

---

## 4 · Coherence (choose one)

| ID | Formula | Phase |
|----|-----------|--------|
| **OPTION_A_SIMPLE** | `1 − |voiceFreq − aiFreq| / maxFreq` (clamped to `[0,1]`) | **Phase-1 (current)** |
| **OPTION_B_DOTPROD** | `dot(voiceSpectrum, aiSpectrum) / (‖v‖ · ‖a‖)` | Phase-2+ (stretch) |

Phase-1 uses **OPTION_A_SIMPLE**. Phase-2 may upgrade to **OPTION_B_DOTPROD** when server sends spectrum vectors.

---

## 5 · Milestones

| Phase | Scope |
|-------|--------|
| **P1** | 100k particles, ≥60 FPS (M3 Pro 16 GB), HTTP telemetry, coherence A |
| **P2** | Server-side storage (`/storage/memories`) replaces ad-hoc local-only flows |
| **P3** | iframe embed → Jarvis dashboard (host `8000`) |
| **P4** | Stretch 200k particles + dot-product coherence |

---

## 6 · File tree (Phase-1)

```text
ui/sound-lab/
  public/
  src/
    core/
      audio.ts       # Web Audio, AnalyserNode FFT 2048
      controller.ts  # Coherence (OPTION_A), blend voice + AI → drive values
      renderer.ts    # three.js scene, InstancedBufferGeometry / instancing, ~100k points
    ui/
      hud.ts         # FPS, latency, particleCount overlay
      params.ts      # lil-gui sliders → tunables
    main.ts          # bootstrap + rAF loop
  index.html
  vite.config.ts
  package.json
```

---

## 7 · Dev command

```bash
cd ui/sound-lab
pnpm dev --host 127.0.0.1 --port 5173
```

Vite may proxy `/api` → `http://127.0.0.1:8787` so the browser calls same-origin `/api/telemetry` during dev.

---

## 8 · Acceptance (Phase-1)

- Safari / Chrome: **≥60 FPS** at 100k particles (typical M3 Pro 16 GB).
- **≤60 ms** average end-to-end latency (telemetry `latencyMs` + HUD rolling average where applicable).
- **Particle count** visible and consistent with renderer instance count.

---

## 9 · Commit convention (example)

```text
feat(sound-lab): phase-1 live particle audio UI
```

---

## 10 · Reference links

- [Three.js — webgl_points_dynamic](https://threejs.org/examples/?q=points#webgl_points_dynamic)
- [Bruno Simon](https://bruno-simon.com)
- [Patatap](https://patatap.com)
- [Penderecki’s Garden — Dwór Mistrza](https://penderckisgarden.pl/pl/dwor-mistrza) *(spelling: Pendercki’s Garden / photogrammetry aesthetic)*
- [Google Experiments](https://experiments.withgoogle.com)

---

## 11 · Next ticket (after P1 success)

- **Phase-2:** Storage migration (`/storage/memories`) + optional **OPTION_B_DOTPROD** when spectra are available.
