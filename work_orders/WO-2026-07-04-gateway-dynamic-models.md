# WO-2026-07-04 — Gateway dynamic model list + health substrate_models

**Status:** QUEUED  
**Priority:** P2 (after daemon dry-run)  
**Created:** 2026-07-04  
**Review gate:** Aether Nexus daemon dry-run **5-day** window ends → owner review before any implementation

## Problem

LM Mini and other OpenAI-compat clients can desync when LM Studio model IDs change but gateway `/v1/models` and upstream `model` field stay hardcoded in `gateway_config.json`.

## Proposed scope (not approved)

1. `GET /v1/models` and `GET /api/v1/models` — live list from `:1234` (filter embeddings), keep `demo/aster`
2. `GET /health` — optional `substrate_models` array for ops
3. `chat_completions` — pass client-selected substrate model when not `demo/aster`
4. Check-only helper script (no kill/restart) to compare config vs LM Studio

## Explicitly out of scope for this WO

- Kill/restart `:8501` or `:8787` from any new script
- Changes to Aster plugin, `aster.toml`, or dual-path deploy
- Tailscale / DNS / LM Mini URL changes (see Scheme 2 verify scripts)

## Acceptance (when implemented)

- `aster_tab_fingerprint_probe.py` PASS (`served_by: gateway-v4.11`)
- LM Mini model list matches `:1234` without manual config edit
- No regression on `demo/aster` generator path

## Notes

Prototype was attempted 2026-07-03 during LM Mini connectivity task and **rolled back** 2026-07-04 for touching gateway structure outside Scheme 2 connectivity-only scope.
