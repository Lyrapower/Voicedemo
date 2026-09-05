#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export FIELD_DIR="${FIELD_DIR:-$HOME/Desktop/GridField}"
export ROUTER_DIR="${ROUTER_DIR:-$ROOT/data/grid_router}"
export NOW_PORT="${NOW_PORT:-8795}"
export NOW_BIND="${NOW_BIND:-127.0.0.1}"
# 验收阶段暂时关闭静默,便于 curl 看到身体/网格;恢复默认: unset NOW_QUIET
export NOW_QUIET="${NOW_QUIET:-}"

mkdir -p "$FIELD_DIR"
chmod 700 "$FIELD_DIR" 2>/dev/null || true

if lsof -ti ":$NOW_PORT" >/dev/null 2>&1; then
  echo "field_now: port $NOW_PORT busy — stop existing listener first" >&2
  exit 1
fi

exec /usr/bin/python3 "$ROOT/scripts/field_now_v1_6.py"
