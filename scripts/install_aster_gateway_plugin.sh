#!/usr/bin/env bash
# Symlink Aster Grid Gateway LM Studio generator plugin (no npm required).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/lmstudio-plugins/aster-grid-gateway"
DEST="$HOME/.lmstudio/extensions/plugins/demo/aster"
LEGACY_DEST="$HOME/.lmstudio/extensions/plugins/demo/aster-grid-gateway"
REF_MOD="$HOME/.lmstudio/extensions/plugins/lmstudio/js-code-sandbox/node_modules"

if [[ ! -d "$SRC" ]]; then
  echo "FAIL: missing $SRC"
  exit 1
fi
if [[ ! -f "$SRC/.lmstudio/production.js" ]]; then
  echo "FAIL: missing prebuilt $SRC/.lmstudio/production.js"
  exit 1
fi

mkdir -p "$(dirname "$DEST")"
ln -sfn "$SRC" "$DEST"
rm -f "$LEGACY_DEST" 2>/dev/null || true
echo "Linked plugin → $DEST"

if [[ -d "$REF_MOD/@lmstudio/sdk" ]]; then
  mkdir -p "$DEST/node_modules"
  ln -sfn "$REF_MOD/@lmstudio" "$DEST/node_modules/@lmstudio"
  echo "Linked @lmstudio/sdk from js-code-sandbox"
else
  echo "WARN: @lmstudio/sdk not found — install LM Studio js-code-sandbox plugin first"
fi

cp -f "$SRC/install-state.json" "$DEST/install-state.json" 2>/dev/null || true

# lms dev -i alone does NOT register the generator after LM Studio restart.
if command -v lms >/dev/null 2>&1; then
  (cd "$SRC" && lms dev -i -y) || echo "WARN: lms dev -i failed — run from $SRC after opening LM Studio"
fi

cat <<'EOF'
OK: demo/aster installed.
  • Model picker → demo/aster (not qwen/qwen3.5-9b)
  • Run: bash scripts/start_aster_gateway_plugin_dev.sh (keeps lms dev running)
EOF
