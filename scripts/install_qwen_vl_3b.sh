#!/usr/bin/env bash
# Install + register Qwen2.5-VL-3B for LM Studio :1234 (vision lane).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="${HOME}/.lmstudio/bin:/opt/homebrew/bin:/usr/local/bin:${PATH}"
LMS="${HOME}/.lmstudio/bin/lms"
VL_ID="${VL_MODEL_ID:-qwen2.5-vl-3b-instruct}"
HF_URL="${VL_HF_URL:-https://huggingface.co/lmstudio-community/Qwen2.5-VL-3B-Instruct-GGUF}"

if ! command -v lms >/dev/null 2>&1; then
  echo "FAIL: lms not found — open LM Studio once or install CLI"
  exit 1
fi

if ! lms ls 2>/dev/null | grep -qi "qwen2.5-vl-3b"; then
  echo "Downloading ${HF_URL} …"
  lms get "${HF_URL}" --yes
fi

echo "Models registered:"
lms ls 2>/dev/null | grep -i vl || true
echo ""
echo "OK: ${VL_ID} ready in LM Studio."
echo "  • Grid app grid.html vision lane → ${VL_ID}"
echo "  • 8790 FIELD particle chat attach/paste image"
echo "  • Gateway :8501 routes image requests → ${VL_ID} on :1234"
echo ""
echo "Optional preload (LM Studio swaps model on first vision request if omitted):"
echo "  lms load ${VL_ID} --ttl 3600"
