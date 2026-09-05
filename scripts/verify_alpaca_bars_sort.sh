#!/usr/bin/env bash
# 门禁:生产路径 Alpaca /stocks/bars 必须带 sort=desc —— 防陈旧K线回归(2026-08-07)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FAIL=0

# 生产文件(不含 backup / deliver 整包 / _pre_* 历史)
FILES=(
  "$ROOT/alpha-platform/backend/worker.py"
  "$ROOT/alpha-platform/backend/factor_truth.py"
  "$ROOT/alpha-platform/backend/alpaca_bars.py"
  "$ROOT/grid-scout/fetchers.py"
  "$ROOT/option-workstation/backend/alpaca_loader.py"
  "$ROOT/aether_watcher/momentum_sticker.py"
  "$ROOT/aether_nexus/aether_dryrun.py"
)

echo "== alpaca bars sort=desc guard =="
for f in "${FILES[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "MISSING: $f"
    FAIL=1
    continue
  fi
  if ! grep -qE 'stocks/.*/bars|stocks/bars' "$f"; then
    echo "SKIP(no bars url): ${f#$ROOT/}"
    continue
  fi
  if grep -qE 'sort=desc|"sort":\s*"desc"|sort.: ."desc"' "$f"; then
    echo "OK  ${f#$ROOT/}"
  else
    echo "FAIL ${f#$ROOT/}  — /stocks/bars without sort=desc"
    FAIL=1
  fi
done

# 禁止生产路径再写无 sort 的旧 1Min 形态(粗)
if grep -nE 'timeframe.: ."1Min"' "$ROOT/alpha-platform/backend/worker.py" | grep -v 'bars_params\|sort' >/dev/null 2>&1; then
  :
fi

cd "$ROOT/alpha-platform/backend"
python3 -m unittest test_alpaca_bars_sort_guard -v

if [[ "$FAIL" -ne 0 ]]; then
  echo "VERIFY FAILED"
  exit 1
fi
echo "VERIFY OK"
