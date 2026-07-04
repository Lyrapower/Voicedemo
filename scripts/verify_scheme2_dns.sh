#!/usr/bin/env bash
# Verify Scheme 2: Split DNS (MagicDNS + NextDNS) + phone -> Mac serve/8501
set -euo pipefail
TS="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
echo "=== Tailscale ==="
$TS status 2>&1 | head -5
$TS serve status 2>&1 | head -8
echo ""
echo "=== Mac local ==="
curl -sf --max-time 3 http://127.0.0.1:8501/health >/dev/null && echo "127.0.0.1:8501 health: OK" || echo "127.0.0.1:8501 health: FAIL"
curl -sf --max-time 5 https://cicimacbook-air.tail76db5b.ts.net/health >/dev/null && echo "Serve HTTPS /health: OK" || echo "Serve HTTPS /health: FAIL"
curl -sf --max-time 5 http://100.72.135.23:8501/health >/dev/null && echo "Tailnet IP :8501 /health: OK" || echo "Tailnet IP :8501 /health: FAIL"
echo ""
echo "=== DNS (Mac) ==="
dig +short cicimacbook-air.tail76db5b.ts.net @100.100.100.100 2>/dev/null | head -1 | xargs -I{} echo "MagicDNS 100.100.100.100 -> {}"
dig +short chatgpt.com @100.100.100.100 2>/dev/null | head -1 | xargs -I{} echo "chatgpt via MagicDNS (expect empty or blocked): {}"
echo ""
echo "=== iPhone verify (manual) ==="
echo "1. Tailscale Connected + Use Tailscale DNS = ON"
echo "2. NextDNS profile installed (2aa2da)"
echo "3. Safari https://cicimacbook-air.tail76db5b.ts.net/health -> JSON ok"
echo "4. Safari https://chatgpt.com -> blocked"
echo "5. LM Mini: https://cicimacbook-air.tail76db5b.ts.net  OR  http://100.72.135.23:8501"
