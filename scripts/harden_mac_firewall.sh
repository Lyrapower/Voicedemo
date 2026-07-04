#!/usr/bin/env bash
# Harden Mac firewall for sovereign stack: gateway/tailnet only, block LAN crawlers to :1234.
set -euo pipefail

echo "=== Grid Sovereign Firewall Hardening ==="

FW="/usr/libexec/ApplicationFirewall/socketfilterfw"

echo "Current firewall state:"
$FW --getglobalstate 2>/dev/null || true
$FW --getstealthmode 2>/dev/null || true

if [ "$(id -u)" -ne 0 ]; then
  echo ""
  echo "Some steps need sudo. Re-run: sudo $0"
  echo ""
fi

# 1. Enable firewall + stealth (ignore ping / reduce scanner visibility)
if [ "$(id -u)" -eq 0 ]; then
  $FW --setglobalstate on
  $FW --setstealthmode on
  $FW --setblockall off
  echo "PASS firewall on + stealth on"
else
  echo "SKIP stealth (needs sudo)"
fi

# 2. LM Studio: localhost only — gateway :8501 talks to 127.0.0.1:1234; no LAN bypass
LM_CFG="$HOME/.lmstudio/.internal/http-server-config.json"
if [ -f "$LM_CFG" ]; then
  python3 <<'PY'
import json
from pathlib import Path
p = Path.home()/".lmstudio/.internal/http-server-config.json"
cfg = json.loads(p.read_text())
if cfg.get("networkInterface") != "127.0.0.1":
    cfg["networkInterface"] = "127.0.0.1"
    p.write_text(json.dumps(cfg, indent=2) + "\n")
    print("PASS LM Studio bind -> 127.0.0.1 (was 0.0.0.0)")
else:
    print("PASS LM Studio already 127.0.0.1")
PY
  if command -v lms >/dev/null 2>&1; then
    lms server stop 2>/dev/null || true
    sleep 1
    lms server start --bind 127.0.0.1 --port 1234 --cors 2>/dev/null || true
    echo "PASS LM Studio server restarted on 127.0.0.1:1234"
  else
    echo "NOTE: restart LM Studio server manually (Developer tab) for bind change"
  fi
fi

# 3. Tailscale: allow (needed for phone -> serve -> gateway)
if [ "$(id -u)" -eq 0 ] && [ -d "/Applications/Tailscale.app" ]; then
  $FW --add /Applications/Tailscale.app 2>/dev/null || true
  $FW --unblockapp /Applications/Tailscale.app 2>/dev/null || true
  echo "PASS Tailscale allowed"
fi

# 4. LM Studio app firewall: block incoming from internet (local gateway uses localhost API)
if [ "$(id -u)" -eq 0 ] && [ -d "/Applications/LM Studio.app" ]; then
  $FW --add "/Applications/LM Studio.app" 2>/dev/null || true
  $FW --blockapp "/Applications/LM Studio.app" 2>/dev/null || true
  echo "PASS LM Studio incoming blocked at firewall (127.0.0.1 still works locally)"
fi

echo ""
echo "=== Stack ports (should be localhost only except Tailscale) ==="
lsof -iTCP -sTCP:LISTEN -P -n 2>/dev/null | grep -E "1234|8501|8787|5173" || true

echo ""
echo "=== Verify ==="
curl -sf --max-time 2 http://127.0.0.1:1234/v1/models >/dev/null && echo "1234 localhost: OK" || echo "1234 localhost: FAIL"
curl -sf --max-time 2 http://127.0.0.1:8501/health >/dev/null && echo "8501 gateway: OK" || echo "8501 gateway: FAIL"
LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || true)
if [ -n "$LAN_IP" ]; then
  if curl -sf --max-time 2 "http://${LAN_IP}:1234/v1/models" >/dev/null 2>&1; then
    echo "WARNING: :1234 still reachable on LAN ${LAN_IP} — restart LM Studio"
  else
    echo "PASS :1234 not reachable on LAN ${LAN_IP}"
  fi
fi
echo ""
echo "Phone path: Tailscale -> https://cicimacbook-air.tail76db5b.ts.net -> gateway :8501"
echo "Do NOT expose :1234 or :8501 to 0.0.0.0"
