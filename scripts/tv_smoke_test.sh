#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v curl >/dev/null 2>&1; then
  echo "FAIL: curl is required"
  exit 1
fi

SECRET="${TRADINGVIEW_WEBHOOK_SECRET:-}"
LOCAL_URL="http://127.0.0.1:8686/webhooks/tradingview"
PUBLIC_URL="${PUBLIC_WEBHOOK_URL:-}"

PAYLOAD="$(python3 - <<'PY'
import json
import os
payload = {
  "source": "tradingview",
  "ticker": "MU",
  "timestamp": "2026-04-24T13:35:00Z",
  "price": 128.4,
  "vwap": 127.2,
  "open_range_high": 128.1,
  "rvol": 1.8,
  "iv_rank": 48,
  "signal": "ORH_VWAP_RVOL_GATE"
}
secret = os.environ.get("TRADINGVIEW_WEBHOOK_SECRET", "").strip()
if secret:
  payload["secret"] = secret
print(json.dumps(payload, separators=(",", ":")))
PY
)"

echo "[local] POST $LOCAL_URL"
LOCAL_BODY="$(curl -sS -w '\nHTTP_STATUS:%{http_code}\n' -X POST "$LOCAL_URL" -H "Content-Type: application/json" -d "$PAYLOAD")"
LOCAL_STATUS="$(printf '%s' "$LOCAL_BODY" | awk -F: '/HTTP_STATUS/{print $2}' | tr -d '[:space:]')"
LOCAL_JSON="$(printf '%s' "$LOCAL_BODY" | sed '/HTTP_STATUS:/d')"
echo "$LOCAL_JSON"

if [ "$LOCAL_STATUS" != "200" ]; then
  echo "FAIL: local webhook status=$LOCAL_STATUS"
  exit 1
fi

if [ -n "$PUBLIC_URL" ]; then
  echo "[public] POST ${PUBLIC_URL%/}/webhooks/tradingview"
  set +e
  PUBLIC_BODY="$(curl -sS -w '\nHTTP_STATUS:%{http_code}\n' -X POST "${PUBLIC_URL%/}/webhooks/tradingview" -H "Content-Type: application/json" -d "$PAYLOAD")"
  PUBLIC_CODE=$?
  set -e
  if [ "$PUBLIC_CODE" -ne 0 ]; then
    echo "UNKNOWN: public webhook curl failed"
    echo "VERIFY_ACTION: check tunnel process and run scripts/tv_tunnel_ngrok.sh or scripts/tv_tunnel_cloudflared.sh"
  else
    PUBLIC_STATUS="$(printf '%s' "$PUBLIC_BODY" | awk -F: '/HTTP_STATUS/{print $2}' | tr -d '[:space:]')"
    PUBLIC_JSON="$(printf '%s' "$PUBLIC_BODY" | sed '/HTTP_STATUS:/d')"
    echo "$PUBLIC_JSON"
    if [ "$PUBLIC_STATUS" != "200" ]; then
      echo "UNKNOWN: public webhook status=$PUBLIC_STATUS"
      echo "VERIFY_ACTION: validate TradingView URL ends with /webhooks/tradingview and secret matches"
    fi
  fi
fi

python3 - <<'PY'
from pathlib import Path
import json

fast = Path('deliver/proof/trading/FAST_GATE_REPORT.md')
if fast.exists():
    lines = fast.read_text(encoding='utf-8', errors='ignore').splitlines()
    print('[FAST_GATE_REPORT summary]')
    for line in lines[-12:]:
        print(line)
else:
    print('FAIL: deliver/proof/trading/FAST_GATE_REPORT.md missing')

events = sorted(Path('data/trading/events').glob('*_tradingview_events.jsonl'))
if events:
    latest = events[-1]
    print(f'[EVENT_LOG latest] {latest.as_posix()}')
    tail = latest.read_text(encoding='utf-8', errors='ignore').splitlines()[-1:]
    for item in tail:
        try:
            payload = json.loads(item)
            print(json.dumps(payload, ensure_ascii=False))
        except Exception:
            print(item)
else:
    print('FAIL: no data/trading/events/*_tradingview_events.jsonl found')
PY
