#!/usr/bin/env bash
# Preflight: verify llama-server exists AND can disable Qwen thinking/reasoning.
# Exit 0 + prints chosen REASONING_FLAGS to stdout (last line).
# Exit 1 on FAIL — do not start server.
set -euo pipefail

if [[ -z "${LLAMA_SERVER:-}" ]]; then
  if [[ -x "/opt/llama.cpp/build/bin/llama-server" ]]; then
    LLAMA_SERVER="/opt/llama.cpp/build/bin/llama-server"
  elif [[ -x "$HOME/opt/llama.cpp/build/bin/llama-server" ]]; then
    LLAMA_SERVER="$HOME/opt/llama.cpp/build/bin/llama-server"
  else
    LLAMA_SERVER="/opt/llama.cpp/build/bin/llama-server"
  fi
fi
MIN_VERSION_HINT="llama.cpp b8460+ (2026-01+) or master with --reasoning off"

if [[ ! -x "$LLAMA_SERVER" ]]; then
  echo "FAIL: llama-server not found at $LLAMA_SERVER" >&2
  echo "Build/install first — see docs/LM_STUDIO_TO_LLAMA_CPP.md" >&2
  exit 1
fi

HELP="$("$LLAMA_SERVER" --help 2>&1)" || {
  echo "FAIL: llama-server --help failed" >&2
  exit 1
}

REASONING_FLAGS=""
if echo "$HELP" | grep -Eq '(^|[[:space:]])--reasoning[[:space:]]'; then
  # Preferred on recent builds: srv init shows "thinking = 0"
  REASONING_FLAGS="--reasoning off"
elif echo "$HELP" | grep -q '\--reasoning-budget'; then
  REASONING_FLAGS="--reasoning-budget 0"
elif echo "$HELP" | grep -q '\--reasoning-format'; then
  REASONING_FLAGS="--reasoning-format none"
else
  echo "FAIL: this llama-server build has NO reasoning-disable flag." >&2
  echo "       Tried: --reasoning off | --reasoning-budget 0 | --reasoning-format none" >&2
  echo "       Required: $MIN_VERSION_HINT" >&2
  echo "       Do NOT pretend success with LM Studio or an old llama.cpp build." >&2
  exit 1
fi

JINJA=""
if echo "$HELP" | grep -q '\--jinja'; then
  JINJA="--jinja"
fi

if [[ "$REASONING_FLAGS" == *"reasoning-budget"* || "$REASONING_FLAGS" == *"reasoning-format"* ]]; then
  if [[ -z "$JINJA" ]]; then
    echo "FAIL: $REASONING_FLAGS requires --jinja but this build lacks --jinja." >&2
    echo "       Required: $MIN_VERSION_HINT" >&2
    exit 1
  fi
  REASONING_FLAGS="$REASONING_FLAGS $JINJA"
fi

echo "OK: llama-server=$LLAMA_SERVER"
echo "OK: reasoning_disable=$REASONING_FLAGS"
echo "$REASONING_FLAGS"
