# Proof Report — Pack 4 · Grid Router (Standalone)

**Date:** 2026-05-24  
**Depends on:** Packs 1–3  
**Status:** COMPLETE · **NOT merged** into `repo/app`  
**Port:** `8792` default (`GRID_ROUTER_PORT`) — Entry B particle remains `repo/app` @ **8787**

---

## Separation (no merge)

| Service | Entry | Port | Module |
|---------|-------|------|--------|
| Grid Router (Pack 4) | Standalone | **8792** | `python -m app.main` |
| Particle + MEMORY (Entry B) | Unchanged | **8787** | `repo/app/main.py` |
| Platform (legacy UI) | Separate | varies | `uvicorn app.platform_main:app` |

No `include_router` from Pack 4 was added to `repo/app/main.py`.

---

## Files created / updated

| Path | Role |
|------|------|
| `app/__init__.py` | `from .main import app` |
| `app/main.py` | Pack 4 FastAPI + lifespan |
| `app/routes.py` | `/route`, `/stream`, `/substrates`, `/audit/{id}` |
| `app/logging_config.py` | Structured logging |
| `app/test_router.py` | 6 unit tests + `--live` |
| `app/platform_main.py` | Previous monolithic `app/main.py` (preserved) |
| `scripts/start_grid_router.sh` | Start Grid Router on 8792 |

---

## Unit test results

```bash
GRID_ROUTER_ALLOW_DEGRADED=1 python3 app/test_router.py
# Ran 6 tests — OK
```

| Test | Result |
|------|--------|
| health | ✅ |
| substrates | ✅ |
| route compile_layer | ✅ |
| carrier `@澄` → cheng | ✅ |
| contamination detection | ✅ |
| audit retrieval | ✅ |

---

## Startup

```bash
./scripts/start_grid_router.sh
# or
GRID_ROUTER_PORT=8792 python -m app.main
```

Requires Ollama + Pack 1 `compile_layer` for live generation.  
Degraded boot (no Ollama): `GRID_ROUTER_ALLOW_DEGRADED=1`.

---

## Live tests (separate terminal)

```bash
python -m app.main   # terminal 1
python3 app/test_router.py --live   # terminal 2
```

---

## Audit log

Success/failure → `logs/router_audit_YYYYMMDD.jsonl`  
App log → `logs/grid_router.log`

---

## Ready for Pack 5

Grid Router runs as its own process; particle/compile UI on 8787 untouched.
