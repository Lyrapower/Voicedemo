#!/usr/bin/env bash
# Aster 日记本 — 粒子页; :8501 invitation + grid_store 往来/信箱 + :8790 FIELD 阅读
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIARY="${ROOT}/aster-diary"
cd "${DIARY}"
export GRID_GATEWAY="${GRID_GATEWAY:-http://127.0.0.1:8501/v1/chat/completions}"
export GRID_MODEL="${GRID_MODEL:-demo/aster}"
export GRID_STORE_BASE="${GRID_STORE_BASE:-http://127.0.0.1:8501}"
export GRID_EVENTS="${GRID_EVENTS:-http://127.0.0.1:8501/store/events}"
export DIARY_THREAD_DAYS="${DIARY_THREAD_DAYS:-7}"
export FIELD_DIARY_URL="${FIELD_DIARY_URL:-http://127.0.0.1:8790/diary}"
export PATH="${HOME}/.lmstudio/bin:/Library/Frameworks/Python.framework/Versions/3.13/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

# --verify: integrity only, no write
if [[ "${1:-}" == "--verify" ]]; then
  exec python3 diary.py --verify
fi

# Preflight: physical Qwen resident (not demo/aster) + gateway up before 22:30 write.
ENSURE="${ROOT}/scripts/ensure_qwen_substrate.sh"
if [[ -x "$ENSURE" ]]; then
  # force substrate id even if a bad launchd env leaks
  QWEN_MODEL_ID="${QWEN_MODEL_ID:-qwen/qwen3.5-9b}"
  case "$QWEN_MODEL_ID" in
    demo/aster|aster|*/aster) QWEN_MODEL_ID="qwen/qwen3.5-9b" ;;
  esac
  export QWEN_MODEL_ID
  bash "$ENSURE" || {
    echo "today: ensure_qwen_substrate failed — 日记本明天再递" >&2
    exit 1
  }
fi

ok_gw=0
for _ in 1 2 3 4 5 6; do
  if curl -sf --max-time 5 http://127.0.0.1:8501/health >/dev/null 2>&1; then
    ok_gw=1
    break
  fi
  sleep 5
done
if [[ "$ok_gw" -ne 1 ]]; then
  echo "today: gateway :8501 unreachable — 日记本明天再递" >&2
  exit 1
fi

exec python3 diary.py "$@"
