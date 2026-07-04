#!/usr/bin/env bash
# Repair 35B weight symlinks so LM Studio can load unsloth/qwen3.6-35b-a3b-mlx-3bit
set -euo pipefail

WEIGHTS="/Volumes/2TB/lmstudio/models/unsloth/qwen3.6-35b-a3b-ud-mlx-3bit"
LM_UNSLOTH="$HOME/.lmstudio/models/unsloth"

if [[ ! -d "$WEIGHTS" ]]; then
  echo "ERROR: 2TB weights not found. Mount 2TB and ensure:"
  echo "  $WEIGHTS"
  exit 1
fi

mkdir -p "$LM_UNSLOTH"
cd "$LM_UNSLOTH"

for name in ".qwen3.6-35b-a3b-ud-mlx-3bit" "qwen3.6-35b-a3b-ud-mlx-3bit"; do
  if [[ -e "$name" && ! -L "$name" ]]; then
    echo "Skip $name (real directory exists)"
    continue
  fi
  ln -sfn "$WEIGHTS" "$name"
  echo "Linked $LM_UNSLOTH/$name -> $WEIGHTS"
done

echo "Done. In LM Studio: unload model → reload unsloth/qwen3.6-35b-a3b-mlx-3bit"
