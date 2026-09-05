#!/usr/bin/env bash
# Install crypto daily signal LaunchAgent (09:05 local, Mon–Fri).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="${ROOT}/scripts/aether/launchd/com.demo.aether.paper-crypto-daily.plist"
DEST="${HOME}/Library/LaunchAgents/com.demo.aether.paper-crypto-daily.plist"
LOG="${HOME}/Library/Logs/demo-aether"
DOMAIN="gui/$(id -u)"
LABEL="com.demo.aether.paper-crypto-daily"

mkdir -p "${LOG}"
chmod +x "${ROOT}/scripts/start_paper_crypto_daily.sh"

SSL_CERT="$(python3 -m certifi 2>/dev/null || "${ROOT}/aether_nexus/.venv/bin/python" -m certifi 2>/dev/null || true)"
sed \
  -e "s|__HOME__|${HOME}|g" \
  -e "s|__DEMO_ROOT__|${ROOT}|g" \
  -e "s|__SSL_CERT_FILE__|${SSL_CERT}|g" \
  "${SRC}" >"${DEST}"

launchctl bootout "${DOMAIN}" "${DEST}" 2>/dev/null || true
sleep 1
launchctl bootstrap "${DOMAIN}" "${DEST}"
launchctl enable "${DOMAIN}/${LABEL}"

echo "OK — paper crypto daily @ 09:05 Mon–Fri (Coinbase/Kraken momentum → crypto inbox)"
