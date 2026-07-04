#!/usr/bin/env bash
# GUI auth harden — uses macOS password dialog (not terminal sudo).
# Double-click in Finder, or: open scripts/harden_mac_firewall_gui.command
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Grid Sovereign Firewall (GUI auth) ==="
echo "A macOS password dialog will appear — enter your Mac login password there."
echo ""

# Non-sudo: LM Studio localhost bind (same as harden_mac_firewall.sh)
bash "$ROOT/scripts/harden_mac_firewall.sh" 2>&1 | sed '/Some steps need sudo/,$d' || true

FW="/usr/libexec/ApplicationFirewall/socketfilterfw"
TS="/Applications/Tailscale.app"
LM="/Applications/LM Studio.app"

read -r -d '' ADMIN_SCRIPT <<EOS || true
set -e
FW="$FW"
\$FW --setglobalstate on
\$FW --setstealthmode on
\$FW --setblockall off
if [ -d "$TS" ]; then
  \$FW --add "$TS" 2>/dev/null || true
  \$FW --unblockapp "$TS" 2>/dev/null || true
fi
if [ -d "$LM" ]; then
  \$FW --add "$LM" 2>/dev/null || true
  \$FW --blockapp "$LM" 2>/dev/null || true
fi
echo STEALTH=\$(\$FW --getstealthmode 2>/dev/null)
echo FIREWALL=\$(\$FW --getglobalstate 2>/dev/null)
EOS

TMP="$(mktemp /tmp/grid_fw_harden.XXXXXX.sh)"
chmod 700 "$TMP"
printf '%s\n' "$ADMIN_SCRIPT" > "$TMP"

RESULT="$(osascript -e "do shell script \"bash '$TMP'\" with administrator privileges" 2>&1)" || {
  rm -f "$TMP"
  echo ""
  echo "CANCELLED or failed. Use System Settings → Network → Firewall manually."
  echo "Opening Firewall settings..."
  open "x-apple.systempreferences:com.apple.Network-Settings.extension?Firewall" 2>/dev/null \
    || open /System/Applications/System\ Settings.app 2>/dev/null || true
  read -r -p "Press Enter to close..."
  exit 1
}
rm -f "$TMP"

echo "$RESULT"
echo ""
echo "=== Post-harden verify ==="
bash "$ROOT/scripts/harden_mac_firewall.sh" 2>&1 | tail -20
echo ""
read -r -p "Done. Press Enter to close..."
