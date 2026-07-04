#!/usr/bin/env bash
# Phone -> Mac Serve diagnostic (run on Mac while iPhone Tailscale = Connected)
set -euo pipefail
TS="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
URL="https://cicimacbook-air.tail76db5b.ts.net/health"
echo "=== Mac Serve ==="
$TS serve status 2>&1 || true
echo "ShieldsUp:" $($TS debug prefs 2>&1 | python3 -c "import json,sys; print(json.load(sys.stdin).get('ShieldsUp'))")
curl -sf --max-time 5 "$URL" && echo "Mac curl: OK" || echo "Mac curl: FAIL"
echo ""
$TS status 2>&1
echo ""
echo "=== iPhone checklist (do IN ORDER) ==="
echo "1. Settings -> VPN: ONLY Tailscale Connected. Remove NextDNS profile (not pause — DELETE profile)."
echo "2. Tailscale app: Connected (green)."
echo "3. Admin ACL -> paste config/tailscale_acl_emergency_open.json -> Save (temporary allow-all)."
echo "4. iPhone Safari: $URL"
echo "5. If still fail: tell assistant exact Safari error (无法连接 / 证书 / 超时)."
