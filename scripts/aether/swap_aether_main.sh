#!/usr/bin/env bash
# 一条命令回滚/恢复 TRADING 主入口(v12 ↔ legacy).
# 用法: swap_aether_main.sh [v12|legacy]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
mode="${1:-legacy}"
case "$mode" in
  v12|legacy) ;;
  *) echo "usage: $0 v12|legacy" >&2; exit 1 ;;
esac
export AETHER_MAIN="$mode"
launchctl setenv AETHER_MAIN "$mode" 2>/dev/null || true
launchctl kickstart -k "gui/$(id -u)/com.demo.grid.gateway8501"
sleep 2
curl -sf "http://127.0.0.1:8501/app/aether.html" | python3 -c "
import sys,re
h=sys.stdin.read()
legacy='renderScanDualSection' in h or '__AETHER_BOOT__' in h
v12='fetchState' in h and 'aether_trading_v12' not in h and 'setFallbackBanner' in h
print('legacy' if legacy else ('v12' if v12 else 'unknown'))
" | {
  read got
  echo "AETHER_MAIN=$mode · served=$got"
  [[ "$got" == "$mode" ]] || exit 1
}
"$ROOT/scripts/tailscale_serve_watchdog.sh" >/dev/null 2>&1 || true
echo "主入口: http://127.0.0.1:8501/app/aether.html"
echo "兜底:   http://127.0.0.1:8501/app/legacy/aether.html"
