# Jarvis Merge Map — minimum safe automation

Generated for: Aether read-only + platform_main sole entry + launchd dry-run templates.

## Sole entry

| Item | Value |
|------|-------|
| **Jarvis entry** | `app.platform_main:app` |
| **Start** | `./scripts/start_jarvis.sh` |
| **Bind** | `127.0.0.1:8686` only |
| **NOT Jarvis** | `app.main:app` (Grid Router, :8792) |
| **NOT Jarvis** | `repo/app/main.py` (Aster :8787) |
| **Task API** | `GET /api/jarvis/tasks` |

---

## Merge map

| Existing module | Jarvis task name | Permission | Schedule | Output artifact | Rollback |
|-----------------|------------------|------------|----------|-----------------|----------|
| **Aether Nexus** (`aether_nexus/`) | `aether.snapshot.readonly` | `signal_only` | manual / hourly plist (Disabled) | `deliver/proof/jarvis/aether_snapshot_latest.json`, `logs/jarvis_tasks/proof_log.jsonl` | Stop sidecar; remove plist; delete snapshot artifact |
| **Aether daemon IB execution** | *(not merged)* | `blocked` | — | — | Keep in sidecar only; never register in Jarvis |
| **Crypto scanner** (`scripts/scan_crypto_rwa_public.py`) | `crypto.scan.dryrun` | `read_only` | Mon 09:00 plist (Disabled) | `logs/jarvis_tasks/proof_log.jsonl` | Unload plist; set `enabled: false` in yaml |
| **Crypto scanner live** | `crypto.scan.run` | `read_only_network` | disabled | `deliver/crypto/evidence/`, `scan_last_run.json` | `enabled: false` in yaml (default) |
| **Crypto compiled memory** | `crypto.proof.compile` | `read_only` | disabled | `knowledge/compiled/WORKSPACE_crypto.md` | Re-run compile; git restore file |
| **Trading readiness** (`jarvis/trading_local_engine.py`) | `trading.readiness.check` | `read_only` | weekdays plist (Disabled) | `DAILY_READINESS_REPORT.md`, proof_log | Unload plist; dry-run only |
| **TradingView webhook** | *(not scheduled)* | `blocked` for live exec | manual only | event jsonl | Keep `tradingview_webhook_enabled: false` |
| **Crypto UI** (`/ui/crypto`) | served by platform_main | `read_only` | on-demand | `outputs/crypto_rwa/` | N/A — already merged |
| **Trading UI** (`/ui/trading`) | served by platform_main + Aether panel | `read_only` | on-demand | trading proof reports | N/A |

---

## Permission levels

| Level | Meaning | Allowed |
|-------|---------|---------|
| `read_only` | Local files, reports, proof logs | ✅ |
| `read_only_network` | Public URL scan (crypto allowlist) | ✅ when task enabled |
| `signal_only` | Read Aether JSON snapshots | ✅ |
| `execution` / `broker` / `wallet` | Orders, signing, funds | ❌ blocked |

---

## Explicitly NOT merged (policy)

- IB auto execution (`aether_daemon.py` orders)
- Trading webhook live execution (`broker_execution: false`)
- Wallet signing / on-chain txs
- Direct broker orders
- Auto fund routing
- New public ports / Tailscale Funnel
- Changes to Aster/Grid/8787 core law

---

## Proof log contract

Every task run writes:

```
logs/jarvis_tasks/proof_log.jsonl   # append-only
logs/jarvis_tasks/{task_id}/latest.json
```

Fields: `run_id`, `task_id`, `ts`, `status`, `permission`, `dry_run`, `artifacts`, `detail`.

---

## Enable launchd (after review)

1. Edit plist paths if repo moved
2. `cp scripts/jarvis/launchd/*.plist ~/Library/LaunchAgents/`
3. Set `<key>Disabled</key><false/>` only for tasks you want
4. `launchctl load ~/Library/LaunchAgents/com.demo.jarvis.crypto-scan-dryrun.plist`

Default shipment: **Disabled=true** for all plists.

---

## Quick verify

```bash
./scripts/start_jarvis.sh &
curl -s http://127.0.0.1:8686/health | python3 -m json.tool
curl -s http://127.0.0.1:8686/api/jarvis/tasks | python3 -m json.tool
./scripts/jarvis_run_task.sh aether.snapshot.readonly --dry-run
```
