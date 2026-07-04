#!/usr/bin/env bash
set -euo pipefail

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "ERROR: cloudflared is not installed."
  echo "Install hint: brew install cloudflared"
  exit 1
fi

LOG_FILE="${TMPDIR:-/tmp}/jarvis_cloudflared_8686.log"
: > "$LOG_FILE"

cloudflared tunnel --url http://127.0.0.1:8686 --no-autoupdate --logfile "$LOG_FILE" >/dev/null 2>&1 &
CF_PID=$!
cleanup() {
  kill "$CF_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

PUBLIC_URL=""
for _ in $(seq 1 60); do
  PUBLIC_URL="$(python3 - <<'PY'
import re
import os
from pathlib import Path
log = Path(os.environ.get('TMPDIR', '/tmp')) / 'jarvis_cloudflared_8686.log'
if not log.exists():
    print('')
else:
    text = log.read_text(encoding='utf-8', errors='ignore')
    match = re.search(r'https://[a-zA-Z0-9.-]+\\.trycloudflare\\.com', text)
    print(match.group(0) if match else '')
PY
)"
  if [ -n "$PUBLIC_URL" ]; then
    break
  fi
  sleep 1
 done

if [ -z "$PUBLIC_URL" ]; then
  echo "ERROR: cloudflared started but no public HTTPS URL detected."
  echo "Check log: $LOG_FILE"
  exit 1
fi

WEBHOOK_URL="${PUBLIC_URL%/}/webhooks/tradingview"
echo "PUBLIC_WEBHOOK_URL=$WEBHOOK_URL"
echo "Keep this script running while TradingView sends alerts."

wait "$CF_PID"
