#!/usr/bin/env bash
# Fix /usr/local/bin/tailscale wrapper (points to missing lowercase binary).
# Run once with: sudo ./scripts/fix_tailscale_cli.sh
set -euo pipefail
TARGET="/usr/local/bin/tailscale"
BIN="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
if [[ ! -x "$BIN" ]]; then
  echo "FAIL: $BIN not found"
  exit 1
fi
cat >"$TARGET" <<EOF
#!/bin/sh
exec "$BIN" "\$@"
EOF
chmod +x "$TARGET"
echo "PASS: $TARGET -> $BIN"
"$TARGET" status | head -5
