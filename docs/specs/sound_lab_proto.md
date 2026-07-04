# Garden (Sound-Lab internal) — live particle audio UI

**Status:** Phase-1 prototype spec (historical). Live UI is `scripts/sound_lab_fallback.py` on **5173**; legacy `ui/sound-lab/` (5200) removed.

*Spec drafted 2026-04-27.*

---

## 1 · Overview

| | |
|--|--|
| **User-facing name** | Garden |
| **Internal repo dir / code refs** | `scripts/sound_lab_fallback.py` (FastAPI + Three.js on **5173**) |
| **Goal** | Show mic voice + AI telemetry (`aiFreq`, `aiAmplitude` / `aiAmp`) as a 3-D particle flow driven by coherence and audio energy. |

---

## 2 · Tech stack

- **FastAPI** + embedded HTML/JS (`scripts/sound_lab_fallback.py`, port **5173**)
- **Aster Router** (`repo/`, port **8787**) reverse-proxies browser traffic to **5173** so **`http://127.0.0.1:8787/`** serves the particle UI.

---

## 3 · Data packet (telemetry)

**Endpoint (FastAPI stub, 方案 A):** `http://127.0.0.1:<TELEMETRY_PORT>/api/telemetry` — default **`8788`** (Aster stays on **8787**).  
**Telemetry stub ➜ 8788**  
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

- `voiceFreq` may be overridden or blended with client-side FFT when the mic is active; server mock may emit a sine-style trajectory until fully wired.
- `latencyMs` is a telemetry hint for HUD (acceptance target ≤60 ms avg).

---

## 4 · Coherence (phase-1 vs phase-2)

**Phase-1 (current):** frequency-difference coherence (simple, cheap):

\[
\text{coherence} = \max\left(0,\ \min\left(1,\ 1 - \frac{|f_{\text{voice}} - f_{\text{ai}}|}{f_{\max}}\right)\right)
\]

**TODO (phase-2):** upgrade to **dot-product / cosine similarity** on aligned spectra when the server sends `voiceSpectrum` and `aiSpectrum` vectors (see previous OPTION_B design). Phase-1 stays on the scalar frequency formula until those payloads exist.

---

## 5 · Milestones

| Phase | Scope |
|-------|--------|
| **P1** | 100k particles, ≥60 FPS (M3 Pro 16 GB), HTTP telemetry, coherence (freq-diff) |
| **P2** | Server-side storage (`/storage/memories`); coherence → dot-product when spectra available |
| **P3** | iframe embed → Jarvis dashboard (host `8000`) |
| **P4** | Stretch 200k particles + full spectrum coherence |

---

## 6 · File tree (Phase-1)

```text
ui/sound-lab/
  public/
  src/
    core/
      audio.ts       # Web Audio, AnalyserNode FFT 2048
      controller.ts  # Coherence (phase-1), blend voice + AI → drive values
      renderer.ts    # three.js scene, instancing, ~100k points
    ui/
      hud.ts         # FPS, latency, particleCount overlay
      params.ts      # lil-gui sliders → tunables
    main.ts          # bootstrap + rAF loop
  index.html
  vite.config.ts
  package.json
telemetry/
  main.py            # GET /api/telemetry, GET /health (stub, default 8788)
repo/app/main.py    # Aster :8787 — middleware proxies GET/HEAD to Vite :5173
```

---

## 7 · Dev commands（终端）

```bash
bash scripts/kill_sound_lab_dev.sh   # optional
bash scripts/start_telemetry_8788.sh # 8788
bash scripts/start_sound_lab.sh      # 5173
cd repo && ./scripts/run.sh          # 8787 Aster + proxy
```

Open **http://127.0.0.1:8787/** for the UI (via proxy). Vite alone: **http://127.0.0.1:5173/**.

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
- [Penderecki’s Garden — Dwór Mistrza](https://penderckisgarden.pl/pl/dwor-mistrza)
- [Google Experiments](https://experiments.withgoogle.com)

---

## 11 · Next ticket (after P1 success)

- **Phase-2:** Storage migration (`/storage/memories`) + spectrum-based coherence (dot-product).
