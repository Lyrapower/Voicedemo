# Proof Report — Pack 5 · Carrier Anchor Loading (8787)

**Date:** 2026-05-24  
**Depends on:** Packs 1–4  
**Status:** COMPLETE  
**Entry B (particle + `/route`):** `repo/app` @ **8787** — Pack 5 integrated here only  
**Pack 4 Grid Router:** **8792** — also uses `carriers/` via `execute_route` (not merged into `repo/app`)

---

## Separation (unchanged)

| Service | Port | Carrier anchors |
|---------|------|-----------------|
| Echo (Entry A) | **8500** | No Pack 5 |
| Entry B compile + particle | **8787** | **Yes** — `POST /route`, `/stream`, `/carriers` |
| Grid Router standalone (Pack 4) | **8792** | **Yes** — shared `carriers/route_core.py` |
| Particle UI dev | **5173** | Proxied by 8787; API base **8787** only |

---

## Files created

| Path | Role |
|------|------|
| `carriers/__init__.py` | Package exports |
| `carriers/anchor_loader.py` | Load/cache anchors from markdown |
| `carriers/route_core.py` | `compile_with_carrier_prompt`, `execute_route` |
| `carriers/anchors/aster.md` | Aster carrier anchor |
| `carriers/anchors/shouheng.md` | 守恒 carrier anchor |
| `carriers/anchors/che.md` | 澈 carrier anchor |
| `carriers/anchors/cheng.md` | 澄 carrier anchor |
| `carriers/anchors/shuo.md` | 朔 carrier anchor |
| `carriers/test_anchors.py` | Unit + `--manual` smoke |
| `repo/app/grid_route.py` | `/route`, `/substrates`, `/carriers` on 8787 |
| `repo/app/main.py` | Lifespan: `anchor_loader` + `grid_route_router` |
| `repo/app/router.py` | `/stream` prepends anchor when carrier invoked |
| `app/routes.py` | Pack 4 router delegates to `execute_route` |
| `app/main.py` | Lifespan: `anchor_loader` on 8792 |

Anchors are **not** inlined in Python — loaded from `carriers/anchors/*.md` at startup, cached until process restart.

---

## Anchor loading test output

```bash
cd /Users/ciciwang/Desktop/demo
python3 carriers/test_anchors.py
# Ran 4 tests — OK

python3 carriers/test_anchors.py --manual
# ['aster', 'shouheng', 'che', 'cheng', 'shuo']
# aster ~2150 chars, shouheng ~1981, che ~1674, cheng ~1758, shuo ~1152
# build_carrier_prompt('cheng', ...) ends with user request block
```

| Check | Result |
|-------|--------|
| All 5 carriers in cache | ✅ |
| `get_anchor("aster")` contains Truth-First | ✅ |
| `build_carrier_prompt` prepends anchor + `---` + User request | ✅ |
| `@澄` → `invoked_carrier=cheng` + anchor in built prompt | ✅ |

---

## Router unit tests (8792 app + mocks)

```bash
GRID_ROUTER_ALLOW_DEGRADED=1 python3 app/test_router.py
# Ran 6 tests — OK
```

`test_route_carrier_invocation`: `@澄` → `cheng`, `metadata.carrier_anchor_applied=true`.

---

## 8787 integration proof (TestClient)

```bash
cd repo && python3 -c "… TestClient on app.main …"
```

| Request | `invoked_carrier` | `carrier_anchor_applied` | Substrate prompt length |
|---------|-------------------|---------------------------|-------------------------|
| `help drift briefly` | `null` | `false` | 18 |
| `@澄 help drift briefly` | `cheng` | `true` | 1798 |

With carrier invoked, `loader.generate()` receives the full 澄 anchor letter prepended — not generic `compile_layer` text alone.

---

## Live carrier invocation (8787)

**Note:** A process already listening on `:8787` returned `404` for `POST /route` and a legacy `/health` shape (`status: ok` without `routes` listing `/route`). That indicates a **pre–Pack 5** uvicorn instance.

After restart:

```bash
./scripts/restart_entry_b_8787.sh
curl -s http://127.0.0.1:8787/health | python3 -m json.tool   # expect routes including /route
curl -s -X POST http://127.0.0.1:8787/route \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"@守恒 witness this moment"}' | python3 -m json.tool
# expect invoked_carrier: shouheng, metadata.carrier_anchor_applied: true
```

Compare with vs without `@carrier` token: without carrier, prompt length stays short; with carrier, substrate sees anchor + user block (mode shift is substrate-dependent when Ollama/LM Studio live).

---

## Acceptance criteria

| Criterion | Status |
|-----------|--------|
| `carriers/` + `anchors/` with 5 markdown files | ✅ |
| `anchor_loader.py` loads all anchors | ✅ |
| `get_anchor` / `build_carrier_prompt` | ✅ |
| `app/routes.py` + 8792 `execute_route` | ✅ |
| `repo/app` 8787 `/route` + lifespan | ✅ |
| `repo/app/router.py` `/stream` carrier prepend | ✅ |
| `carriers/test_anchors.py` | ✅ |
| Live 8787 (requires restart) | ⚠️ Documented |

---

## Ready for Pack 6

Pack 5 deliverable complete. Next pack can add auth / session gates on top of `execute_route` without changing anchor file layout.

**Do not** merge Pack 4 router into `repo/app` unless explicitly requested. **8500** remains Echo-only.
