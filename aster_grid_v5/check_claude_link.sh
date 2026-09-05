#!/usr/bin/env bash
# Verify Claude Code CLI ↔ V5.1 sentinel link (run in Terminal.app).
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh
LOG="${ASTER_GRID_V5_ROOT}/traces/claude_link_check.log"
mkdir -p "$(dirname "$LOG")"
exec > >(tee "$LOG") 2>&1

echo "=== claude binary ==="
command -v claude
claude --version

echo ""
echo "=== sentinel status ==="
python3 sentinel_ledger_v5.py init | python3 -c "import sys,json; d=json.load(sys.stdin); print('claude_bin_present:', d.get('claude_bin_present'))"

echo ""
echo "=== referee probe (fable) ==="
CLAUDE_TIMEOUT="${CLAUDE_TIMEOUT:-90}" python3 sentinel_ledger_v5.py referee --role fable "回答一个词:在岗"

echo ""
echo "PASS: claude_link_check"
