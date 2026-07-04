#!/usr/bin/env bash
# DEMO_MODE=1 + SQLite (dev.db) + 2 min scheduler. No Docker.
set -euo pipefail
export DEMO_MODE=1
export DEMO_CHECK_INTERVAL_MIN="${DEMO_CHECK_INTERVAL_MIN:-2}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec bash "$ROOT/scripts/run_dev.sh"
