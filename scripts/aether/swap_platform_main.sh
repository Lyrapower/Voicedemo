#!/usr/bin/env bash
# 一条命令回滚/恢复 PLATFORM 主入口(v11 ↔ react).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
mode="${1:-react}"
case "$mode" in
  v11|react) ;;
  *) echo "usage: $0 v11|react" >&2; exit 1 ;;
esac
export PLATFORM_MAIN="$mode"
(cd "$ROOT/alpha-platform" && docker compose up -d --force-recreate api)
sleep 2
html="$(curl -sf "http://127.0.0.1:8600/app/")"
if [[ "$mode" == "v11" ]]; then
  echo "$html" | rg -q 'hedge-body' || { echo "FAIL: /app/ not v11"; exit 1; }
  echo "PLATFORM_MAIN=v11 · /app/ → 守恒 v1.1(含避险观察)"
else
  echo "$html" | rg -q 'Alpha Platform' || { echo "FAIL: /app/ not react"; exit 1; }
  echo "PLATFORM_MAIN=react · /app/ → React 运维台(legacy)"
fi
echo "React 兜底: http://127.0.0.1:8600/app/react/"
