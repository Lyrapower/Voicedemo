# Garden Shader Upgrade — Proof Report

**Date:** 2026-05-19  
**Scope:** Volumetric `ShaderMaterial` upgrade for live particle field (5173 only)

---

## 1. Files modified

| File | Change |
|------|--------|
| `scripts/sound_lab_fallback.py` | Replaced legacy per-layer `uKind`/`uAmp` shaders with spec volumetric vertex + fragment shaders; added `color` + `size` geometry attributes; uniform routing to `uAmplitude` / `uSizeMultiplier` |

**No new separate `.glsl` files** — shader sources embedded inline (same pattern as prior implementation).

**Backend:** Not touched (`8787`, `live_tts.py`, `garden_api.py` unchanged).

---

## 2. Particle count

```
42000 + 32000 + 15000 + 15000 + 9000 + 52000 = 165000
```

Unchanged.

---

## 3. Shader implementation checklist

| Requirement | Status |
|-------------|--------|
| `ShaderMaterial` (not `PointsMaterial`) | ✅ |
| Spec vertex shader (distance attenuation + amplitude size mod) | ✅ |
| Spec fragment shader (`smoothstep` core + `exp` halo + `discard`) | ✅ |
| `AdditiveBlending` | ✅ |
| `depthWrite: false` | ✅ |
| `depthTest: true` | ✅ |
| `transparent: true` | ✅ |
| `vertexColors: true` | ✅ |
| `size` attribute on all layer geometries | ✅ |
| `uAmplitude` ← existing `drive.amp` (+ layer/contrast scaling) | ✅ |
| `uSizeMultiplier` ← `controls.size` (Particle Size slider) | ✅ |
| Shader compile once at init | ✅ |
| No extra draw calls (6 layers, same as before) | ✅ |

---

## 4. FPS verification

**Manual browser check required.**

Open `http://127.0.0.1:8787/` (or `:5173`), DevTools → Performance, confirm **≥60 FPS** with 165k particles at default settings on target hardware (M2 16GB).

Automated headless WebGL benchmark not run in this pass.

---

## 5. Latency verification

**Manual check required.**

HUD `latency ~N ms` should remain **≤25 ms** under normal MIC load (baseline was ~18 ms). No changes to telemetry or audio analysis path.

---

## 6. Visual verification

**Expected vs previous:**

| Before | After |
|--------|-------|
| Custom masks per layer (`uKind` rings/edges) | Uniform volumetric sprite: sharp core + exponential halo |
| Square-edge risk on some sprites | Circular `discard` boundary |
| Per-fragment HSL fringe rings | Layer base colors via vertex `color` attribute |
| Additive glow | Spec `core * 1.0 + halo * 0.4` alpha |

Each point should read as a **bright center + soft glow**, with additive bloom where particles overlap.

---

## 7. Functional verification

| Feature | Expected | Code path touched |
|---------|----------|-------------------|
| MIC audio reactivity | ✅ Unchanged | `computeParticleDrive`, `animateLayer`, `uAmplitude` |
| Dispersion slider | ✅ Unchanged | plume offset in tick |
| Particle Size slider | ✅ Routes to `uSizeMultiplier` | tick loop |
| Contrast slider | ✅ Scales `uAmplitude` per layer | tick loop |
| Depth / Mouse / Flow / Flow Amp / Dance / Depth Wave | ✅ Unchanged | animate + camera |
| Live Analyzer | ✅ Unchanged | DOM only |
| PRESENCE button | ✅ Unchanged | `/api/presence` |
| SAVE MEMORY button | ✅ Unchanged | UI only |
| Session HUD (fps, latency, coh, timer) | ✅ Unchanged | tick HUD |
| TTS / 8787 | ✅ Not modified | — |

---

## 8. Parameter tuning (post visual QA)

**Diagnosis:** Initial spec parameters made the field look **smaller and sparser** than the pre-upgrade shader despite similar `gl_PointSize`. Primary cause was **fragment falloff**, not vertex point radius.

| Old behavior | New (initial spec) | Effect |
|--------------|-------------------|--------|
| `haloMask = smoothstep(0.72, 0.2, r)` — wide visible glow | `exp(-dist² × 4.0)` — tight falloff | Halo dies off fast → sparse field |
| Core alpha up to ~1.06 + amp | Core only bright inside 20% radius | Tiny hot center |
| Layer alpha 0.78–1.06 × depthFade | `core + halo×0.4` max ~1.4 but concentrated | Lower perceived luminosity |
| `196/-z × depthScale` vertex sizing | `300/-z` only | Minor vs fragment |

**Adjusted values:**

| Parameter | Was | Now | Why |
|-----------|-----|-----|-----|
| **Core smoothstep threshold** | `0.2` | **`0.35`** | Wider bright core (main visual size fix) |
| **Halo exp coefficient** | `4.0` | **`2.2`** | Softer, wider exponential glow |
| **Halo alpha weight** | `0.4` | **`0.88`** | Restores additive bloom density |
| **Core alpha weight** | `1.0` | **`1.08`** | Slightly brighter center |
| **RGB luminance boost** | none | **`vColor × (core×1.18 + halo×0.62)`** | Matches old per-layer brightness multipliers |
| **`distanceFactor` coefficient** | `300.0` | **`420.0`** | Compensates old `196 × depthScale` average (~1.1×) |
| **`uSizeMultiplier` base** | `controls.size × 1.8` | **`controls.size × 2.65`** | Restores sprite diameter vs old `uSize` default |

Core + halo + `AdditiveBlending` structure unchanged. 165k particle count unchanged.

---

## 9. Deviations from spec (with justification)

1. **Six materials retained** (core, halo, 3 fringes, dust) — spec shows single material; existing architecture uses 6 draw layers.
2. **Per-layer `uAmplitude` scaling preserved** — same audio source, layer weights unchanged.
3. **Fringe ring/edge fragment masks removed** — base fringe colors via vertex `color`.
4. **Color Shift Speed (hidden)** — no runtime `uShift` tint on dust.
5. **Fragment + size tuning (§8)** — spec-default coefficients too tight vs legacy visual mass.

---

## 10. v2 aesthetic pass (2026-05-19)

**Shader — 场域深邃清澈 (depth + clarity):**
- Added uniforms: `uTime`, `uCoherence`, `uEnergy`, `uBaseColor`, `uGlowIntensity`
- Vertex: non-linear `depthFactor`, coherence-tight sizing, energy boost
- Fragment: core + halo + energy bloom; depth-modulated alpha `(0.42 + (1-vDepth)*0.58)`
- Per-layer `uBaseColor`: gold-left / cyan-right field separation

**Silhouette:**
- Tighter `profile()` (shoulder/torso/waist)
- Core/halo surface pow `0.30` (denser body shell)
- Lateral bias: green/coral left, cyan right

**Motion (existing MIC bands, no new analysis pipeline):**
- Low-freq breathe + high-freq ripple × coherence in `animateLayer`
- Coherence tightens formation when high

**UI:**
- Field controls: cyan mono panel aesthetic
- Live Analyzer: coherence gradient bar, activity opacity
- Presence button: gold-active state

**Not implemented (out of scope):** Particle LOD, new audio analyzer, 8787 changes.

---

## 11. How to verify locally

```bash
# Terminal 1
python3 -m uvicorn scripts.sound_lab_fallback:app --host 127.0.0.1 --port 5173

# Terminal 2 (optional, for full stack)
cd repo && uvicorn app.main:app --host 127.0.0.1 --port 8787
```

Open `http://127.0.0.1:8787/`, enable MIC, toggle Presence, confirm volumetric particles + controls + analyzer.
