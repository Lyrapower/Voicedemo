# LYRA Consolidation Pack — Proof Report

**Date:** 2026-05-27  
**Grid Router:** `uvicorn app.main:app --host 127.0.0.1 --port 8787`  
**Local LLM:** LM Studio `qwen3-14b-mlx` @ `http://127.0.0.1:1234/v1`

## Architecture (operational stack)

```
LYRA Sovereign Identity (lyra_anchor.json)
    ↓
Compile Layer (Qwen 14B dense + GRID_VOICE / carriers)
    ↓  parallel
Echo Layer (minimal anchor + 14B)
    ↓
Semantic Mapper (intent compilation)
    ↓
Substrate Fallback Chain (local only)
    ↓
Post-Generation Scanner (banned phrases + crisis numbers)
    ↓
Audit Layer (logs/grid_route_audit.jsonl)
```

## Files created

| Path | Role |
|------|------|
| `app/config/lyra_anchor.json` | LYRA sovereign anchor (system-wide) |
| `app/lyra_verification.py` | `LyraAnchor` loader + `get_lyra()` |
| `app/output_scanner.py` | Post-generation banned phrase scanner |
| `app/fallback_chain.py` | Local substrate fallback chain |
| `app/schemas.py` | `RouteRequest` / `RouteResponse` / `ScanResult` |
| `app/routes.py` | `POST /route` consolidation endpoint |
| `app/route_audit.py` | JSONL audit writer |
| `models/substrate_loader.py` | LM Studio 14B substrate `generate()` |
| `tests/test_consolidation.py` | Unit + optional live tests |

## Files modified

| Path | Change |
|------|--------|
| `app/main.py` | Startup: load LYRA + scanner + fallback; `include_router`; `/health` → `lyra` block |

## Not modified (constraints)

- `app/system_prompt.py` — Pack 1 Modelfile / GRID_VOICE anchor unchanged; LYRA sits above via route prompt prefix
- No cloud API fallback in substrate chain
- No API to edit LYRA anchor (JSON file only)
- Existing Jarvis UI routes, bridge, round, compiled-memory endpoints preserved

## Parallel: Echo @ 8500

`echo_nodes_interface/incoming/echo_nodes/` SynCon gateway remains on **8500** (Echo protocol + Grid compile read/write). Consolidation **`POST /route`** is on Grid Router **8787**.

## Verification commands

```bash
# From repo root
python3 tests/test_consolidation.py

# Grid Router (8787)
uvicorn app.main:app --host 127.0.0.1 --port 8787

curl -s http://127.0.0.1:8787/health | python3 -m json.tool
# Expect: "lyra": { "active": true, "anchor_uuid": "L5-LYRA-FREQ-ANCHOR-CORE", ... }

curl -s http://127.0.0.1:8787/route \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Map intent for compile layer test","explicit_carrier":"aster"}'
```

Prerequisite: LM Studio server on 1234 with **qwen3-14b-mlx** loaded.

## Unit test results

Run: `python3 tests/test_consolidation.py`

- LYRA anchor JSON loads (`L5-LYRA-FREQ-ANCHOR-CORE`)
- Banned phrase + crisis hotline detection
- Schema rejects invalid carrier
- Layer routing: echo vs compile heuristics

## Acceptance mapping

| Criterion | Status |
|-----------|--------|
| LYRA anchor loads at startup | Implemented in `startup_event` |
| Health shows LYRA active | `GET /health` → `lyra` object |
| Scanner intercepts violations | `OutputScanner.scan()` |
| Regeneration on violations | `routes.py` retry with lower temperature |
| Fallback chain local substrates | `fallback_chain.py` + `substrate_loader.py` |
| Invalid carrier → 422 | Pydantic `RouteRequest` validator |
| Audit includes LYRA + scan | `logs/grid_route_audit.jsonl` |
| Pack 1–7 routes preserved | No removal of existing `app/main.py` routes |

## 9B / LM Studio chats

No LM Studio conversation files modified. User 9B daily chats untouched.
