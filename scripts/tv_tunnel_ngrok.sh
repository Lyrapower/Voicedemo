#!/usr/bin/env bash
set -euo pipefail

if ! command -v ngrok >/dev/null 2>&1; then
  echo "ERROR: ngrok is not installed."
  echo "Install hint: brew install ngrok"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required."
  exit 1
fi

LOG_FILE="${TMPDIR:-/tmp}/jarvis_ngrok_8686.log"
: > "$LOG_FILE"

ngrok http http://127.0.0.1:8686 --log=stdout >"$LOG_FILE" 2>&1 &
NGROK_PID=$!
cleanup() {
  kill "$NGROK_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

PUBLIC_URL=""
for _ in $(seq 1 40); do
  PUBLIC_URL="$(python3 - <<'PY'
import json
import urllib.request
try:
    with urllib.request.urlopen('http://127.0.0.1:4040/api/tunnels', timeout=1.0) as r:
        data = json.load(r)
    tunnels = data.get('tunnels', [])
    https_urls = [t.get('public_url', '') for t in tunnels if str(t.get('public_url', '')).startswith('https://')]
    print(https_urls[0] if https_urls else '')
except Exception:
    print('')
PY
)"
  if [ -n "$PUBLIC_URL" ]; then
    break
  fi
  sleep 1
 done

if [ -z "$PUBLIC_URL" ]; then
  echo "ERROR: ngrok started but no public HTTPS URL detected."
  echo "Check log: $LOG_FILE"
  exit 1
fi

WEBHOOK_URL="${PUBLIC_URL%/}/webhooks/tradingview"
echo "PUBLIC_WEBHOOK_URL=$WEBHOOK_URL"
echo "Keep this script running while TradingView sends alerts."

wait "$NGROK_PID"
