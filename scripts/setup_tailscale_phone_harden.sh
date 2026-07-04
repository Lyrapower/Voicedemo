#!/usr/bin/env bash
# Tailscale iPhone hardening — ACL + Shields Up checklist + DNS blocklist reference.
# Does NOT change Mac ports 8501/8510/8520. Phone uses Serve HTTPS only for LM Mini.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TS="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
POLICY="$ROOT/config/tailscale_phone_harden.policy.json"
DNS_BLOCK="$ROOT/config/nextdns_phone_ai_block.txt"
ACL_URL="https://login.tailscale.com/admin/acls"
MACHINES_URL="https://login.tailscale.com/admin/machines"

if [[ ! -x "$TS" ]]; then
  echo "FAIL: Tailscale.app not found at /Applications/Tailscale.app"
  exit 1
fi

echo "=== Mac-side auto (this machine) ==="
# Mac Shields Up must stay OFF — otherwise iPhone cannot reach Tailscale Serve (:443).
$TS set --shields-up=false --accept-routes=false --exit-node= 2>/dev/null || true
echo "Mac Shields Up: OFF (required for phone Serve) | accept-routes: OFF | exit-node: none"
$TS serve status 2>&1 | head -5 || true
curl -sf --max-time 3 http://127.0.0.1:8501/health >/dev/null && echo "Gateway :8501 health: OK" || echo "Gateway :8501 health: FAIL (start gateway first)"
echo ""
echo ""

echo "--- Mac tailnet status ---"
$TS status 2>&1 || true
echo ""
echo "--- Serve (LM Mini path) ---"
$TS serve status 2>&1 || true
echo ""

MAC_HOST="$($TS status --json 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
self_=d.get('Self',{})
print(self_.get('DNSName','').rstrip('.') or self_.get('HostName',''))
" 2>/dev/null || echo "cicimacbook-air.tail76db5b.ts.net")"

PHONE_NAME="$($TS status --json 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
for p in d.get('Peer',{}).values():
    if (p.get('OS') or '').lower().startswith('ios'):
        print(p.get('HostName') or p.get('DNSName','').split('.')[0] or 'iphone')
        break
else:
    print('iphone-13-pro-max')
" 2>/dev/null || echo "iphone-13-pro-max")"

SERVE_URL="https://${MAC_HOST}"
if [[ "$MAC_HOST" != *".ts.net" ]]; then
  SERVE_URL="https://${MAC_HOST}.tail76db5b.ts.net"
fi

echo "=== What this does ==="
echo "1. Tailnet ACL: iPhone (tag:mobile-client) -> Mac :443 ONLY (Tailscale Serve -> gateway :8501)"
echo "2. iPhone Shields Up: block inbound scans to the phone on tailnet"
echo "3. NextDNS on iPhone: block cloud AI / crawler domains on cellular+WiFi"
echo "4. Mac sidecar ports unchanged: 8501 gateway, 8510 Nexus, 8520 Watcher"
echo ""

echo "=== STEP A — Admin console (Mac browser, ~3 min) ==="
echo "1. Open ACL editor: $ACL_URL"
echo "2. Replace policy with: $POLICY"
echo "   (Remove the // comment line if the editor rejects JSON — it is a note only.)"
echo "3. Save — tests must pass (phone allowed :443, denied raw ports)."
echo "4. Open machines: $MACHINES_URL"
echo "5. Tag Mac  ($($TS status 2>/dev/null | awk '/macOS/{print $2; exit}')) -> tag:sovereign-mac"
echo "6. Tag iPhone ($PHONE_NAME) -> tag:mobile-client"
echo ""

echo "=== STEP B — iPhone Tailscale app (~2 min) ==="
echo "1. Open Tailscale → … menu → Use Tailscale DNS: ON (after NextDNS profile, see Step C)"
echo "2. Enable **Shields Up** (blocks other tailnet devices from connecting TO your phone)"
echo "3. Exit Node: **None** (do not route all internet via another device)"
echo "4. Allow incoming connections: **OFF** / Shields Up handles this"
echo "5. Subnet routes: **OFF** unless you explicitly need them"
echo "6. Stay logged in; reconnect after tagging in Step A"
echo ""

echo "=== STEP C — Block cloud AI + crawlers on iPhone (~5 min) ==="
echo "Tailscale ACL cannot block ChatGPT/Claude apps on the public internet — use DNS:"
echo "1. Sign up: https://nextdns.io (free tier OK)"
echo "2. Enable blocklists: AI, Chat, Native Tracking, Threat Intelligence"
echo "3. Denylist file in repo: $DNS_BLOCK"
echo "4. iOS: NextDNS app → Install Configuration Profile → allow VPN/DNS"
echo "5. Settings → General → VPN & Device Management → verify NextDNS profile"
echo ""

echo "=== STEP D — iOS system hardening (recommended) ==="
echo "• Settings → Screen Time → App Limits: block or limit AI apps you do not trust"
echo "• Settings → Privacy → Tracking: **Allow Apps to Request to Track: OFF**"
echo "• Settings → Privacy → Analytics: disable Share iPhone Analytics"
echo "• Optional: Settings → Privacy & Security → Lockdown Mode (max protection)"
echo "• Never install unsigned MDM / 'free VPN' profiles from unknown sites"
echo ""

echo "=== STEP E — LM Mini (unchanged) ==="
echo "Server URL in LM Mini:"
echo "  $SERVE_URL"
echo "Do NOT point LM Mini at :1234 or raw tailnet IP:8501 — use Serve HTTPS only."
echo ""

echo "=== Verify (after Step A tagging) ==="
echo "From iPhone Safari (on tailnet): open $SERVE_URL/health — should return JSON OK"
echo "From iPhone: raw http://100.x.x.x:8501 should FAIL (ACL deny)"
echo ""

if command -v open >/dev/null 2>&1; then
  read -r -p "Open Tailscale ACL admin in browser now? [y/N] " ans || ans="n"
  case "$ans" in
    [yY]|[yY][eE][sS]) open "$ACL_URL" ;;
  esac
fi

echo "Done. Policy file: $POLICY"
