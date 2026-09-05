#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export ROUTER_DIR="${ROUTER_DIR:-$ROOT/data/grid_router}"
export ROUTER_PORT="${ROUTER_PORT:-8500}"
exec /usr/bin/python3 "$ROOT/scripts/grid/grid_router.py"
