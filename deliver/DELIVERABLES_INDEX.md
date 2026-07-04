# Deliverables Index — cross-checked 2026-07-02

Single map of **code → runtime → proof**. Regenerate proofs: `./scripts/accept_all_deliverables.sh`

---

## A. iCloud Downloads → Aether Watcher

| Source (Downloads) | Repo path | Runtime | Proof |
|--------------------|-----------|---------|-------|
| `aether watcher 2.py` | `aether_watcher/aether_watcher.py` | `./aether_watcher/run_watcher.sh` | `deliver/proof/aether_watcher/ACCEPTANCE_REPORT.md` |
| `watcher dashboard.py` | `aether_watcher/watcher_dashboard.py` | `./aether_watcher/run_dashboard.sh` → `:8520` | same |
| `watch targets 2.toml` | `aether_watcher/watch_targets.toml` | hot reload | same |
| `watcher env example.env` | `aether_watcher/.env.example` | copy → `.env` | — |
| `aether watcher.pdf` | `docs/aether_watcher/aether_watcher.pdf` | reference | — |
| `sound lab fallback v2.py` | **SKIP** | `scripts/sound_lab_fallback.py` (newer v2.1) | `deliver/proof/garden_shader_upgrade/` |
| `watch targets.toml` | **SKIP** (subset of v2) | — | — |

**Runtime artifacts (daemon running):**

| File | Purpose |
|------|---------|
| `aether_watcher/state/heartbeat.json` | Daemon liveness + target summary |
| `aether_watcher/state/watch_state.json` | Per-target baselines |
| `aether_watcher/state/events.json` | Trigger stream for dashboard |
| `aether_watcher/state/watcher.log` | Daemon log |

**Accept:** `./scripts/accept_aether_watcher.sh`

---

## B. Crypto 板块 (pre-existing + Jarvis tasks)

| Layer | Path | UI / API | Proof |
|-------|------|----------|-------|
| Docs / evidence | `deliver/crypto/` | — | `deliver/proof/crypto/ACCEPTANCE_REPORT*.md` |
| Generator | `app/crypto_rwa/generator.py` | — | functional report |
| Workbench UI | `app/platform_main.py` | `GET /ui/crypto` | v0_3 + functional |
| Scanner | `scripts/scan_crypto_rwa_public.py` | Jarvis task `crypto.scan.dryrun` | `deliver/crypto/scan_last_run.json` |
| Outputs | `outputs/crypto_rwa/` | export-pack actions | `crypto_rwa_pack_status.json` |

**Accept:**

- `./scripts/accept_crypto_v0_3.sh` (uses **platform_main**)
- `./scripts/accept_crypto_rwa_functional.sh`
- `./scripts/jarvis_run_task.sh crypto.scan.dryrun --dry-run`

---

## C. Jarvis automation merge (not wired to watcher)

| Item | Path | Proof |
|------|------|-------|
| Sole entry | `scripts/start_jarvis.sh` → `:8686` | `deliver/proof/jarvis/ACCEPTANCE_REPORT.md` |
| Task registry | `config/jarvis_automation.yaml`, `app/jarvis/` | `logs/jarvis_tasks/proof_log.jsonl` |
| Aether read-only adapter | `app/jarvis/aether_readonly_adapter.py` | `deliver/proof/jarvis/aether_snapshot_latest.json` |
| Merge map | `deliver/jarvis/JARVIS_MERGE_MAP.md` | — |
| launchd (Disabled) | `scripts/jarvis/launchd/*.plist` | README in same dir |

**Accept:** `./scripts/accept_jarvis_automation.sh`

---

## D. Trading / Aether Nexus (sidecars — not Jarvis execution)

| Module | Path | Port | Jarvis link |
|--------|------|------|-------------|
| Aether Nexus | `aether_nexus/` | IB 7497, UI 8510 | Watcher `OptionScanner` only |
| TradingView | `jarvis/trading_local_engine.py` | webhook `:8686` | manual-only gates |
| Garden | `scripts/sound_lab_fallback.py` | `:5173` | separate from watcher |

---

## E. Master acceptance

```bash
./scripts/accept_all_deliverables.sh
```

Writes: `deliver/proof/DELIVERABLES_ACCEPTANCE.md`

---

## F. Explicitly NOT merged

- IB auto execution via Jarvis
- Wallet / broker / live trading webhook
- Watcher ↔ Jarvis platform_main (by design)
- Public ports (all bind `127.0.0.1`)
