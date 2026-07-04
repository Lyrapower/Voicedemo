#!/usr/bin/env bash
# llama.cpp OpenAI-compat server — Qwen3.5-9B Q4_K_M, localhost only.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MODEL_DIR="/Volumes/2TB/models/qwen"
MODEL_FILE="${MODEL_FILE:-$MODEL_DIR/Qwen3.5-9B-Q4_K_M.gguf}"
if [[ -z "${LLAMA_SERVER:-}" ]]; then
  if [[ -x "/opt/llama.cpp/build/bin/llama-server" ]]; then
    LLAMA_SERVER="/opt/llama.cpp/build/bin/llama-server"
  elif [[ -x "$HOME/opt/llama.cpp/build/bin/llama-server" ]]; then
    LLAMA_SERVER="$HOME/opt/llama.cpp/build/bin/llama-server"
  else
    LLAMA_SERVER="/opt/llama.cpp/build/bin/llama-server"
  fi
fi
HOST="127.0.0.1"
PORT="${PORT:-1234}"       # use PORT=1235 for compare mode (LM Studio keeps 1234)
COMPARE_MODE="${COMPARE_MODE:-0}"
ALIAS="qwen/qwen3.5-9b"   # matches gateway openai_model — endpoint-only switch
CTX="${CTX:-8192}"
NGPU="${NGPU:-99}"
LOG_DIR="${LOG_DIR:-/tmp/grid-llama-qwen}"
PID_FILE="$LOG_DIR/llama-qwen.pid"

mkdir -p "$LOG_DIR"

if [[ ! -f "$MODEL_FILE" ]]; then
  echo "FAIL: model missing: $MODEL_FILE" >&2
  echo "Download: huggingface-cli download bartowski/Qwen_Qwen3.5-9B-GGUF \\" >&2
  echo "  --include 'Qwen3.5-9B-Q4_K_M.gguf' --local-dir '$MODEL_DIR'" >&2
  exit 1
fi

REASONING_FLAGS="$(bash "$ROOT/scripts/substrate/llama_qwen_preflight.sh" | tail -1)"
if [[ -n "${SHADOW_EXTRA_FLAGS:-}" ]]; then
  REASONING_FLAGS="$SHADOW_EXTRA_FLAGS"
fi

TEMP="${SHADOW_TEMP:-0.3}"
TOP_P="${SHADOW_TOP_P:-0.9}"
TEMPLATE_KWARGS="${SHADOW_CHAT_TEMPLATE_KWARGS:-}"

EXTRA_ARGS=()
if [[ -n "$TEMPLATE_KWARGS" ]]; then
  EXTRA_ARGS+=(--chat-template-kwargs "$TEMPLATE_KWARGS")
fi

# Production switch uses 1234 — must stop LM Studio first.
# Compare mode uses PORT=1235 — LM Studio on 1234 stays untouched.
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  if [[ "$COMPARE_MODE" == "1" && "$PORT" != "1234" ]]; then
    echo "FAIL: compare port $PORT already in use" >&2
    lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >&2 || true
    exit 1
  fi
  echo "WARN: port $PORT in use — stop LM Studio server before llama.cpp on :1234" >&2
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >&2 || true
  exit 1
fi

CMD=(
  "$LLAMA_SERVER"
  --model "$MODEL_FILE"
  --alias "$ALIAS"
  --host "$HOST"
  --port "$PORT"
  --ctx-size "$CTX"
  --n-gpu-layers "$NGPU"
  --threads "$(sysctl -n hw.logicalcpu 2>/dev/null || echo 4)"
  --temp "$TEMP"
  --top-p "$TOP_P"
)
if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
  CMD+=("${EXTRA_ARGS[@]}")
fi
# shellcheck disable=SC2206
CMD+=($REASONING_FLAGS)
exec "${CMD[@]}"
