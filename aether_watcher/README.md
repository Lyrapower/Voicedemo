# Aether Watcher V0.2

7×24 monitoring sidecar: price / RSS / webpage / **scanner_health** (Aether Nexus R5.4.1).

**Not connected to Jarvis** — file-based state only, localhost dashboard.

## Quick start

```bash
cd aether_watcher
cp .env.example .env   # optional: Pushover / Telegram / Anthropic
./run_watcher.sh       # daemon → state/
./run_dashboard.sh     # http://127.0.0.1:8520
```

## Config

- Targets: `watch_targets.toml` (hot reload, no restart)
- V0.2 additions: `scanner_health`, Alpaca `headers_env` on price targets
- OptionScanner points at `../aether_nexus/` dryrun logs + signals

## State files

| File | Role |
|------|------|
| `state/heartbeat.json` | Daemon liveness + target summary |
| `state/events.json` | Trigger stream (dashboard) |
| `state/watch_state.json` | Per-target baselines |
| `state/watcher.log` | Daemon log |

## Docs

Reference PDF: `docs/aether_watcher/aether_watcher.pdf`

## Skipped duplicate

`sound lab fallback v2.py` — repo `scripts/sound_lab_fallback.py` is **newer** (field morph, state badge, echo). No downgrade applied.
