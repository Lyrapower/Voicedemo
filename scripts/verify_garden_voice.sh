#!/usr/bin/env bash
# Garden GridVoice static + gateway chain smoke (no browser mic).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GARDEN="${GARDEN_URL:-http://127.0.0.1:5173}"
GW="${GRID_GATEWAY:-http://127.0.0.1:8501}"

ok() { echo "PASS: $*"; }
bad() { echo "FAIL: $*"; exit 1; }

echo "=== Garden HTML markers ($GARDEN) ==="
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
if ! curl -sf -m 3 "$GARDEN/" -o "$TMP" 2>/dev/null; then
  if ! curl -sf -m 3 "http://127.0.0.1:8787/" -o "$TMP" 2>/dev/null; then
    bad "Garden not reachable on 5173 or 8787"
  fi
fi
rg -q 'voiceBtn|resolveGardenGw|GridVoice' "$TMP" || bad "GridVoice markers missing in Garden HTML"
rg -q 'voiceKhSave|grid_keyholder' "$TMP" || bad "keyholder UI missing"
ok "Garden HTML has GridVoice + keyholder UI"

echo "=== Gateway voice assets ==="
curl -sf -m 3 "$GW/app/grid_voice.js" | rg -q 'class GridVoice' || bad "grid_voice.js not served"
curl -sf -m 3 "$GW/app/grid_keyholder.js" | rg -q 'GridKeyholder' || bad "grid_keyholder.js not served"
ok "8501 serves grid_voice.js + grid_keyholder.js"

echo "=== Voice daemon ==="
curl -sf -m 3 http://127.0.0.1:8504/health | rg -q 'grid-voice-daemon' || bad "8504 voice daemon down"
ok "8504 voice daemon health"

echo "=== Gateway challenge (keyholder prereq) ==="
curl -sf -m 3 -X POST "$GW/challenge/new" | rg -q 'nonce' || bad "challenge/new failed"
ok "8501 challenge/new"

echo "=== All garden voice static checks passed ==="
