# Downloads integration log (2026-07-02)

| Source file | Action | Target |
|-------------|--------|--------|
| `sound lab fallback v2.py` | **SKIP** — repo newer | `scripts/sound_lab_fallback.py` already has v2.1 morph |
| `watch targets.toml` | **SKIP** — subset of v2 | use `watch targets 2.toml` only |
| `watch targets 2.toml` | **ADD** | `aether_watcher/watch_targets.toml` |
| `aether watcher 2.py` | **ADD** | `aether_watcher/aether_watcher.py` |
| `watcher env example.env` | **ADD** | `aether_watcher/.env.example` |
| `watcher dashboard.py` | **ADD** | `aether_watcher/watcher_dashboard.py` |
| `aether watcher.pdf` | **ADD** (reference) | `docs/aether_watcher/aether_watcher.pdf` |

Jarvis: **not wired** (per request).

Smoke test: `OptionScanner` scanner_health read OK against `aether_nexus/dryrun.log` + `dryrun_state/signals.json`.
