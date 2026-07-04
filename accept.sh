#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

mkdir -p deliver/proof/trading
REPORT="deliver/proof/trading/WEBHOOK_LIVE_ACCEPTANCE.md"

STARTED_BY_SCRIPT=0
UVICORN_PID=""

if lsof -nP -iTCP:8686 -sTCP:LISTEN >/dev/null 2>&1; then
  SERVER_STATUS="running"
else
  SERVER_STATUS="started_by_accept"
  STARTED_BY_SCRIPT=1
  python3 -m uvicorn app.platform_main:app --host 127.0.0.1 --port 8686 >/tmp/jarvis_accept_uvicorn.log 2>&1 &
  UVICORN_PID=$!
  sleep 2
fi

cleanup() {
  if [ "$STARTED_BY_SCRIPT" -eq 1 ] && [ -n "$UVICORN_PID" ]; then
    kill "$UVICORN_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

EVENT_BEFORE_FILE=""
EVENT_BEFORE_LINES=0
if ls data/trading/events/*_tradingview_events.jsonl >/dev/null 2>&1; then
  EVENT_BEFORE_FILE="$(ls -1t data/trading/events/*_tradingview_events.jsonl | head -1)"
  EVENT_BEFORE_LINES="$(wc -l < "$EVENT_BEFORE_FILE" | tr -d '[:space:]')"
fi

set +e
SMOKE_OUTPUT="$(bash scripts/tv_smoke_test.sh 2>&1)"
SMOKE_CODE=$?
set -e

FAST_REPORT="deliver/proof/trading/FAST_GATE_REPORT.md"
EVENT_AFTER_FILE=""
EVENT_NEW=false
if ls data/trading/events/*_tradingview_events.jsonl >/dev/null 2>&1; then
  EVENT_AFTER_FILE="$(ls -1t data/trading/events/*_tradingview_events.jsonl | head -1)"
  AFTER_LINES="$(wc -l < "$EVENT_AFTER_FILE" | tr -d '[:space:]')"
  if [ -z "$EVENT_BEFORE_FILE" ]; then
    EVENT_NEW=true
  elif [ "$EVENT_AFTER_FILE" != "$EVENT_BEFORE_FILE" ]; then
    EVENT_NEW=true
  elif [ "$AFTER_LINES" -gt "$EVENT_BEFORE_LINES" ]; then
    EVENT_NEW=true
  fi
fi

PASS=true
REASONS=()
if [ "$SMOKE_CODE" -ne 0 ]; then
  PASS=false
  REASONS+=("tv_smoke_test failed")
fi
if [ ! -f "$FAST_REPORT" ]; then
  PASS=false
  REASONS+=("FAST_GATE_REPORT missing at $FAST_REPORT")
fi
if [ "$EVENT_NEW" != "true" ]; then
  PASS=false
  REASONS+=("event jsonl was not updated")
fi

NOW_UTC="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
{
  echo "# TradingView Live Webhook Acceptance"
  echo
  echo "Generated: $NOW_UTC"
  echo "Server status: $SERVER_STATUS"
  echo
  echo "## Checks"
  if [ "$SMOKE_CODE" -eq 0 ]; then
    echo "- PASS - webhook returns 200 for local smoke payload"
  else
    echo "- FAIL - webhook smoke call failed"
  fi
  if [ -f "$FAST_REPORT" ]; then
    echo "- PASS - proof report exists: $FAST_REPORT"
  else
    echo "- FAIL - proof report missing: $FAST_REPORT"
  fi
  if [ "$EVENT_NEW" = "true" ]; then
    echo "- PASS - events jsonl updated: $EVENT_AFTER_FILE"
  else
    echo "- FAIL - events jsonl not updated"
  fi
  echo
  echo "## Smoke Output"
  echo '```'
  printf '%s\n' "$SMOKE_OUTPUT"
  echo '```'
  echo
  echo "## Proof Paths"
  echo "- deliver/proof/trading/FAST_GATE_REPORT.md"
  echo "- deliver/proof/trading/WEBHOOK_LIVE_ACCEPTANCE.md"
  echo "- ${EVENT_AFTER_FILE:-data/trading/events/*_tradingview_events.jsonl}"
  echo
  if [ "$PASS" = true ]; then
    echo "FINAL VERDICT: PASS"
  else
    echo "FINAL VERDICT: FAIL"
    echo "FAILED_CHECKS:"
    for reason in "${REASONS[@]}"; do
      echo "- $reason"
    done
  fi
} > "$REPORT"

if [ "$PASS" = true ]; then
  echo "PASS"
  echo "deliver/proof/trading/FAST_GATE_REPORT.md"
  echo "deliver/proof/trading/WEBHOOK_LIVE_ACCEPTANCE.md"
  echo "${EVENT_AFTER_FILE:-data/trading/events/*_tradingview_events.jsonl}"
  exit 0
fi

echo "FAIL"
echo "deliver/proof/trading/FAST_GATE_REPORT.md"
echo "deliver/proof/trading/WEBHOOK_LIVE_ACCEPTANCE.md"
echo "${EVENT_AFTER_FILE:-data/trading/events/*_tradingview_events.jsonl}"
for reason in "${REASONS[@]}"; do
  echo "FAILED: $reason"
done
exit 1
