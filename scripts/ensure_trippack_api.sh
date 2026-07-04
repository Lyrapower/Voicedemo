#!/usr/bin/env bash
# Run from Xcode (SRCROOT/.. = repo root). Non-fatal: never fails the build.
set +e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if curl -sS -m 1 "http://127.0.0.1:8810/health" 2>/dev/null | grep -q '"ok"'; then
  exit 0
fi
cd "$ROOT/trippack_api" || exit 0
mkdir -p data
if [[ ! -d .venv ]]; then python3 -m venv .venv; fi
# shellcheck source=/dev/null
source .venv/bin/activate
pip install -q -r requirements.txt
export TRIPPACK_BACKEND_MODE="${TRIPPACK_BACKEND_MODE:-DEBUG_DEMO}"
nohup uvicorn app.main:app --host 127.0.0.1 --port 8810 >>/tmp/trippack_xcode.log 2>&1 &
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  sleep 0.4
  if curl -sS -m 1 "http://127.0.0.1:8810/health" 2>/dev/null | grep -q '"ok"'; then
    exit 0
  fi
done
exit 0
