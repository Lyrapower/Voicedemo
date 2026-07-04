#!/usr/bin/env bash
# Find 35B weights on any mounted volume and repair LM Studio symlink.
set -euo pipefail

LM_UNSLOTH="$HOME/.lmstudio/models/unsloth"
TARGET_NAME=".qwen3.6-35b-a3b-ud-mlx-3bit"
DEFAULT="/Volumes/2TB/lmstudio/models/unsloth/qwen3.6-35b-a3b-ud-mlx-3bit"

echo "=== Fix 35B load path ==="
echo

RAM_GB="$(($(sysctl -n hw.memsize) / 1024 / 1024 / 1024))"
echo "System RAM: ${RAM_GB} GB (hub recommends ~18 GB+ for this model)"
if [[ "$RAM_GB" -lt 18 ]]; then
  echo "WARN: 16 GB Mac often OOM on 35B. Use context 8192–16384 and close other apps."
fi
echo

WEIGHTS=""
if [[ -f "$DEFAULT/config.json" ]]; then
  WEIGHTS="$DEFAULT"
  echo "Found default path: $WEIGHTS"
else
  echo "Default not found: $DEFAULT"
  echo "Searching /Volumes for config.json ..."
  while IFS= read -r cfg; do
  dir="$(dirname "$cfg")"
  if [[ "$(basename "$dir")" == *35b* ]] || [[ "$(basename "$dir")" == *35B* ]]; then
    WEIGHTS="$dir"
    echo "Found: $WEIGHTS"
    break
  fi
  done < <(find /Volumes -maxdepth 8 -name "config.json" 2>/dev/null | grep -i 35b || true)
fi

if [[ -z "$WEIGHTS" ]]; then
  echo
  echo "FAIL: No 35B weights on any mounted disk."
  echo
  echo "Do ONE of the following:"
  echo "  1) Plug in the 2TB drive until Finder shows it (may not be named '2TB')."
  echo "  2) In LM Studio: Download 'unsloth/Qwen3.6-35B-A3B-UD-MLX-3bit' to internal SSD."
  echo "  3) Use 9B instead: qwen/qwen3.5-9b (works on 16 GB)."
  exit 1
fi

mkdir -p "$LM_UNSLOTH"
ln -sfn "$WEIGHTS" "$LM_UNSLOTH/$TARGET_NAME"
ln -sfn "$WEIGHTS" "$LM_UNSLOTH/qwen3.6-35b-a3b-ud-mlx-3bit"
echo
echo "Linked:"
echo "  $LM_UNSLOTH/$TARGET_NAME -> $WEIGHTS"
ls -la "$LM_UNSLOTH/$TARGET_NAME"
echo
echo "Next:"
echo "  1) LM Studio → Unload model"
echo "  2) Load: unsloth/qwen3.6-35b-a3b-mlx-3bit"
echo "  3) Context Length: 16384 (16 GB Mac) or 32768 (24 GB+)"
echo "  4) Or CLI: lms load unsloth/qwen3.6-35b-a3b-mlx-3bit --context-length 16384"
