# Jarvis · Voice Garden

Real-time audio-reactive particle field (Three.js **InstancedMesh**, WebGL2), Web Audio + **Meyda**, optional **WebSocket** stream `ws://localhost:8787/live`, **IndexedDB** session cards (WAV + particle keyframes), and a **lil-gui** settings panel.

## Prerequisites

- Node.js 20+ and npm

## Setup

```bash
cd garden
npm install
npm run dev
```

Open the URL Vite prints (typically `http://localhost:5173`).

## Controls

- **Mic on / Mic off**: requests microphone permission when first enabled, then runs Meyda feature extraction (RMS, spectral centroid, dominant frequency estimate, simple onset “beat”).
- **Record session / Stop**: captures mono **WAV** (float → 16-bit PCM in-browser), appends **particle keyframes** every 2 seconds (`particles_keyframes.json` content is stored as a string blob alongside metadata in IndexedDB), and refreshes the **Memory corridor** list.
- **Session card (scroll-snap list)**: click to enter **playback** — audio plays and uniforms are driven from interpolated keyframes; live orbit is paused during playback.
- **Garden panel (lil-gui, right)**: dispersion, particle size, flow speed, audio reactivity, bloom intensity, color shift speed, particle count (50k–200k).

## WebSocket payload

Connect to `ws://localhost:8787/live` and send JSON lines:

```json
{ "t": 12.3, "aiFreq": 440, "aiAmplitude": 0.2 }
```

If the server is down, a **mock generator** supplies similar samples at 20 Hz.

## Coherence

`coherence = 1 - min(|voiceFreq - aiFreq|, maxFreq) / maxFreq` with `maxFreq = 8000` Hz, clamped to `[0,1]`, then blended with RMS and AI amplitude for particle uniforms.

## Latency overlay

Bottom-left shows averaged **FPS** and **audio→visual** delay sampled every 60 frames (time from last Meyda callback to the following compositor frame). Use it to sanity-check the ≤80 ms target on your machine.

## Production build and zip artifact

```bash
npm run build
npm run zip
```

`npm run zip` writes **`garden-dist.zip`** inside the `garden/` folder (zip of **`dist/`** after a successful build).

A **source-only** archive of this folder may also exist at the monorepo root as `garden-dist.zip` for hand-off; replace it with `npm run zip` output when you need the real production bundle.

## Phase 2

`src/api.ts` stubs `POST /memory/save` for future FastAPI + `storage/memories/{id}/`. Comment in file: **Phase 2 migration target — server storage, NOT File System API** (Safari/iOS compatible path uses `fetch` + blobs only).

## Acceptance checklist (local)

Run on **M3 Pro 16 GB** (or similar): verify **≥60 FPS** at **100k** particles, latency overlay **≤80 ms** with mic on, **replay** feels instant (IndexedDB read + `Audio` start; heavy sessions depend on WAV size).

## References

- [Three.js dynamic points](https://threejs.org/examples/?q=points#webgl_points_dynamic)
- [Bruno Simon](https://bruno-simon.com) — Three.js craft
- [Patatap](https://patatap.com) — audio reactivity inspiration

(Google Experiments / Penderecki garden URLs were not fetched here; add your own mood links if needed.)
