#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)/aether_nexus"
cd "$ROOT"
PY="${PY:-$ROOT/.venv/bin/python}"
exec "$PY" post_market_summary_daemon.py "$@"
