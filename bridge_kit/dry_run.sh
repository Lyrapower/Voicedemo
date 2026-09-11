#!/usr/bin/env bash
# dry_run.sh — 戌接线顺序的全程演练(只读 + 只写指定的 stream 文件)。
# 用法:bash bridge_kit/dry_run.sh <receipts.jsonl> <grid_input_stream.txt> [repo=.] [EGRESS.md] [local_gateway.py]
# 沙箱里用假 receipts 跑一遍;真机换真路径跑同一条。每步失败即停,退出码非 0。
set -euo pipefail
REC="${1:?receipts.jsonl}"; STREAM="${2:?grid input stream}"; REPO="${3:-.}"; EGRESS="${4:-EGRESS.md}"; GW="${5:-local_gateway.py}"
KIT="$(cd "$(dirname "$0")" && pwd)"; cd "$KIT/.."
echo "== 0 selfcheck";        python3 bridge_kit/selfcheck.py 2>/dev/null | tail -1
echo "== 1 site_probe";       python3 bridge_kit/site_probe.py --repo "$REPO" --egress "$EGRESS" --gateway "$GW" --stream "$STREAM" ${NO_NET:+--no-net}
echo "== 2 backfill (1st)";   python3 bridge_kit/grid_inbound.py "$REC" "$STREAM"
echo "== 2 backfill (2nd, all duplicate expected)"; python3 bridge_kit/grid_inbound.py "$REC" "$STREAM"
echo "== 3 wire_verify";      python3 bridge_kit/wire_verify.py --receipts "$REC" --stream "$STREAM"
echo "== 4 e2e_synthetic";    python3 bridge_kit/e2e_synthetic.py | tail -1
echo "== DRY_RUN_OK"
