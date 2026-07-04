#!/usr/bin/env bash
# Quick checks when Entry A / LM Studio shows errors everywhere.
set -euo pipefail

ENI_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ECHO_DIR="$ENI_ROOT/incoming/echo_nodes"
WEIGHTS_2TB="/Volumes/2TB/lmstudio/models/unsloth/qwen3.6-35b-a3b-ud-mlx-3bit"
LM_UNSLOTH="$HOME/.lmstudio/models/unsloth"
CONV="$HOME/.lmstudio/conversations/17797865158101.conversation.json"

echo "=== Echo Nodes Entry A diagnostics ==="
echo

fail=0
ok() { echo "  OK: $*"; }
bad() { echo "  FAIL: $*"; fail=1; }

# 1) External drive
if [[ -d /Volumes/2TB ]]; then
  ok "2TB volume mounted"
else
  bad "2TB not mounted — plug in external drive (any volume name), run fix_35b_load.sh"
fi

if [[ -d "$WEIGHTS_2TB" ]]; then
  ok "35B weights folder on 2TB"
else
  bad "Missing weights: $WEIGHTS_2TB"
fi

# 2) Symlinks LM Studio uses
for name in ".qwen3.6-35b-a3b-ud-mlx-3bit" "qwen3.6-35b-a3b-ud-mlx-3bit"; do
  p="$LM_UNSLOTH/$name"
  if [[ -L "$p" ]] && [[ -e "$p" ]]; then
    ok "symlink $name -> $(readlink "$p")"
  elif [[ -d "$p" ]]; then
    ok "directory $name (not symlink)"
  else
    bad "missing or broken: $p"
  fi
done

# 3) Hub card
if [[ -f "$HOME/.lmstudio/hub/models/unsloth/qwen3.6-35b-a3b-mlx-3bit/model.yaml" ]]; then
  ok "hub card unsloth/qwen3.6-35b-a3b-mlx-3bit"
else
  bad "hub card missing"
fi

# 4) Conversation
if [[ -f "$CONV" ]]; then
  ok "LM Studio chat: Echo Nodes Interface ($CONV)"
else
  bad "conversation missing — run install_lmstudio_dual_entry.sh"
fi

# 5) Python executor
if python3 -c "import sys; sys.path.insert(0, '$ECHO_DIR'); from echo_nodes_fastapi import app" 2>/dev/null; then
  ok "echo_nodes_fastapi imports"
else
  bad "echo_nodes_fastapi import failed (run: pip3 install -r $ECHO_DIR/requirements.txt)"
fi

if curl -sf --max-time 2 http://127.0.0.1:8500/health >/dev/null 2>&1; then
  ok "FastAPI on :8500 running"
else
  echo "  WARN: FastAPI not running (optional). Start: cd $ECHO_DIR && ./start.sh"
fi

PROMPT="$ENI_ROOT/prompts/echo_nodes_system.txt"
if [[ -f "$PROMPT" ]] && grep -q "LYRA ANCHOR" "$PROMPT" && grep -q "SYNCON LAB" "$PROMPT"; then
  ok "LM Studio prompt includes LYRA + SynCon ($(wc -c < "$PROMPT" | tr -d ' ') bytes)"
else
  bad "prompt missing LYRA/SynCon — run: python3 $ENI_ROOT/setup/build_echo_system_prompt.py && $ENI_ROOT/setup/apply_lmstudio_entry_a.sh"
fi

echo
echo "=== What 'all errors' usually means ==="
echo "  A) LM Studio: model not loaded / 2TB unplugged → red banner on chat"
echo "  B) LM Studio: context 131072 too large → lower to 65536 in Load settings"
echo "  C) Entry A persona: minimal/silent replies are intentional, not UI errors"
echo "  D) Echo API not running only matters if you use http://127.0.0.1:8500"
echo
if [[ $fail -eq 0 ]]; then
  echo "Infrastructure looks OK. If LM Studio still errors, copy the exact red text."
else
  echo "Fix failures above, then run: $ENI_ROOT/setup/repair_lmstudio_35b_path.sh"
fi
exit $fail
