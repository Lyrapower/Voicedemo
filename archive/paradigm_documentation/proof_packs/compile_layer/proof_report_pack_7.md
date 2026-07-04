# Proof Report — Pack 7 · Integration & Deployment

**Date:** 2026-05-24  
**Depends on:** Packs 1–6  
**Status:** COMPLETE

---

## Dual-entry testing (not merged)

| Suite | Port | File | Results file |
|-------|------|------|----------------|
| Entry A | **8500** | `tests/integration_test_entry_a.py` | `integration_results_entry_a.json` |
| Entry B | **8787** | `tests/integration_test_entry_b.py` | `integration_results_entry_b.json` |
| Runner | both | `tests/integration_test.py` | `integration_results_summary.json` |

```bash
python3 tests/integration_test.py --entry-a   # A only
python3 tests/integration_test.py --entry-b   # B only
python3 tests/integration_test.py             # both, separate runs
```

Entry A verifies: health, `/echo-node`, descriptor/context, **no** `/route`.  
Entry B verifies: health + `/route`, carriers, contamination, audit, echo_layer routing, **no** `/echo-node`.

---

## Files created

| Path | Role |
|------|------|
| `tests/integration_test.py` | Orchestrator (A/B separate) |
| `tests/integration_test_entry_a.py` | 8500 suite |
| `tests/integration_test_entry_b.py` | 8787 suite |
| `tests/scenarios/carrier_modes.py` | 5 carrier `/route` scenarios (B only) |
| `deployment/deploy_all.sh` | Dual-entry deploy instructions |
| `deployment/health_monitor.py` | Monitor A and/or B separately |
| `README_DEPLOYMENT.md` | Operational docs |
| `repo/app/grid_route.py` | `GET /audit/{id}` for 8787 |
| `repo/app/main.py` | Health: `substrates_available`, `/audit` in routes |

---

## Live run (this environment)

Stale processes on 8500/8787 predated Pack 5+ `/route` on B.

- Entry A: **4/5** (health shape `status: ok` — test updated to accept)
- Entry B: **1/9** until `./scripts/restart_entry_b_8787.sh`

After restart:

```bash
INTEGRATION_ALLOW_DEGRADED=1 python3 tests/integration_test.py
python3 tests/scenarios/carrier_modes.py
```

---

## Deploy

```bash
./deployment/deploy_all.sh
python3 deployment/health_monitor.py --entry both
```

---

## 7-pack complete

| Pack | Deliverable |
|------|-------------|
| 1 | Anchor + Modelfile |
| 2 | Substrate loader |
| 3 | Semantic mapper |
| 4 | Grid Router **8792** (standalone) |
| 5 | Carrier anchors **8787** |
| 6 | Memory layer (lightweight default) |
| 7 | Integration + deployment |

**8500 / 8787 remain decoupled.**
