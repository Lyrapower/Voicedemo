#!/usr/bin/env bash
# LM Mini / Scheme 2 — check and report ONLY (no kill, no restart).
# See PORT_PROCESS_CONVENTION.md
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== LM Mini connectivity check (read-only) ==="
echo ""

FAIL=0

if curl -sf --max-time 3 http://127.0.0.1:1234/v1/models >/dev/null 2>&1; then
  echo "PASS LM Studio :1234"
else
  echo "FAIL LM Studio :1234 — load chat model + enable Local Server"
  FAIL=1
fi

if curl -sf --max-time 3 http://127.0.0.1:8501/health >/dev/null 2>&1; then
  echo "PASS gateway :8501"
  curl -sf http://127.0.0.1:8501/health | python3 -m json.tool | head -15
else
  echo "FAIL gateway :8501 — restart via launchctl only:"
  echo "  launchctl kickstart -k \"gui/\$(id -u)/com.demo.grid.gateway8501\""
  FAIL=1
fi

echo ""
echo "=== Scheme 2 DNS / Serve ==="
bash "$ROOT/scripts/verify_scheme2_dns.sh" || FAIL=1

echo ""
echo "=== LM Mini settings (Scheme 2) ==="
echo "Server URL: https://cicimacbook-air.tail76db5b.ts.net"
echo "Fallback:   http://100.72.135.23:8501"
echo "Model:      demo/aster  OR  qwen/qwen3.5-9b"
echo ""
echo "iPhone: Tailscale Connected + Use Tailscale DNS = ON"

exit "$FAIL"
