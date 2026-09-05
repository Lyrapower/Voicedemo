#!/usr/bin/env bash
# 从已运行的 Theta Terminal 拉一日 EOD → data/raw/
# 用法:
#   bash scripts/theta_ingest.sh              # SPY · 昨交易日
#   bash scripts/theta_ingest.sh QQQ 2026-08-01
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SYM="${1:-SPY}"
DATE="${2:-}"
export THETA_BASE="${THETA_BASE:-http://127.0.0.1:25503}"
export OWS_DATA="${OWS_DATA:-$ROOT_DIR/data}"
cd "$ROOT_DIR/backend"
ARGS=(theta_loader.py --root "$SYM")
[[ -n "$DATE" ]] && ARGS+=(--date "$DATE")
exec python3 "${ARGS[@]}"
