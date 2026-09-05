#!/usr/bin/env bash
# Expose Grid Sovereign Gateway (:8501) on Tailscale — v4.3 compliant (127.0.0.1 bind + tailscale serve).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT=8501

if ! command -v tailscale >/dev/null 2>&1; then
  echo "FAIL: tailscale CLI not found. Install from https://tailscale.com/download"
  exit 1
fi

TS_IP="$(tailscale ip -4 2>/dev/null || true)"
if [[ -z "$TS_IP" ]] || tailscale status 2>&1 | grep -q NeedsLogin; then
  echo "Tailscale is not logged in (NeedsLogin)."
  echo "1. Open Tailscale from the menu bar / Applications"
  echo "2. Sign in with your tailnet account"
  echo "3. Re-run: $0"
  open -a Tailscale 2>/dev/null || open "/Applications/Tailscale.app" 2>/dev/null || true
  exit 1
fi

if ! curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  echo "Gateway not up on :${PORT} — starting..."
  "$ROOT/scripts/start_grid_gateway.sh" &
  sleep 2
fi

VOICE_PORT=8504
if ! curl -sf "http://127.0.0.1:${VOICE_PORT}/health" >/dev/null 2>&1; then
  echo "Voice daemon not up on :${VOICE_PORT} — starting..."
  "$ROOT/scripts/start_voice_daemon.sh" &
  sleep 2
fi

if ! curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  echo "FAIL: gateway still not reachable at http://127.0.0.1:${PORT}/health"
  exit 1
fi

if ! curl -sf "http://127.0.0.1:${VOICE_PORT}/health" >/dev/null 2>&1; then
  echo "WARN: voice daemon not reachable at http://127.0.0.1:${VOICE_PORT}/health (mic WS will fail)"
fi

echo "PASS gateway health on 127.0.0.1:${PORT}"
curl -sf "http://127.0.0.1:${PORT}/health" | python3 -c "
import sys,json
d=json.load(sys.stdin)
v=d.get('voice') or {}
print('  voice:', v.get('status','?'), 'asr', v.get('asr'), 'tts', v.get('tts'))
" 2>/dev/null || true

# Reset prior serve config for this port, then expose gateway (background).
tailscale serve reset 2>/dev/null || true
tailscale serve --bg "http://127.0.0.1:${PORT}"

echo ""
echo "=== Tailscale Serve active ==="
tailscale serve status 2>&1 || true
echo ""
HOST="$(tailscale status --json 2>/dev/null | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    self=d.get('Self',{})
    dns=self.get('DNSName','').rstrip('.')
    print(dns or self.get('HostName',''))
except Exception:
    print('')
" 2>/dev/null || true)"

echo "Tailscale IPv4: ${TS_IP}"
if [[ -n "$HOST" ]]; then
  echo "MagicDNS:       https://${HOST}"
  echo ""
  echo "LM Mini → Settings → Server URL:"
  echo "  https://${HOST}"
  echo "(OpenAI-compatible: /v1/chat/completions · /v1/models)"
else
  echo ""
  echo "LM Mini → Settings → Server URL:"
  echo "  http://${TS_IP}:${PORT}"
fi
echo ""
echo "Test from iPhone (Safari, Tailscale must show Connected):"
echo "  https://${HOST:-$TS_IP}/health"
echo "  https://${HOST:-$TS_IP}/app/grid.html   (Grid + voice mic)"
echo "  https://${HOST:-$TS_IP}/app/aether.html"
echo "  https://${HOST:-$TS_IP}/app/changyu.html"
echo "  wss://${HOST:-$TS_IP}/voice              (voice WS via gateway proxy)"
echo "  DO NOT use http:// or :8501 on phone — gateway binds 127.0.0.1 only; phone path is Serve HTTPS :443"
echo ""
echo "Stop serve: tailscale serve reset"
