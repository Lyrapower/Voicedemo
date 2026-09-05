# WO-ASTER-FIELD — formal repo / modular split

**Status:** QUEUED (after FIELD v1 deploy acceptance)  
**Created:** 2026-07-04  
**Parent:** ASTER FIELD v1 @ :8790 (monolith in `grid-sovereign-runtime/field/`)

## Goal

Promote ASTER FIELD from two-file deploy to a formal repo layout with CI, without changing shader/state semantics.

## Target layout

```
grid-sovereign-runtime/field/   # or sibling repo aster-field/
  backend/
    app.py          # FastAPI entry (from aster_field_bridge.py)
    state_bus.py    # Bus + SSE /state
    relay.py        # POST /chat stream relay + state derivation
    telemetry.py    # garden :8787 poll + gateway health poll
  frontend/
    index.html      # interim until Vite migration
    field/
      shaders/*.glsl
      state/machine.ts
      hud/
      tokens.ts     # visual params extracted from aster_field_v1.html
  tests/
    test_state_derivation.py   # Fable four-scene baseline
  requirements.txt
```

## Migration rules

- Shader uniforms + `W_OF` state mapping **must not change semantics** during split
- `POST /chat` remains pass-through to `:8501`; zero gateway edits
- Deploy stays `:8790` LaunchAgent `com.demo.field.bridge8790`

## CI minimum

- `pytest tests/`
- `tsc --noEmit` (after frontend TS extraction)
- Run on every PR touching `field/`

## PR convention (post-split)

Each field iteration: PR diff + short change note appended under `work_orders/` or PR body template:

- Visual / state / relay / telemetry scope tag
- Acceptance: four items from `field_v1_acceptance.md` unchanged unless explicitly revised

## Acceptance (unchanged from v1)

1. HUD bridge + gateway green @ :8790  
2. thinking → output ripple → idle  
3. `served_by: gateway-v4.11` in reply meta  
4. LM Studio stop → error 0.5s → idle, no crash
