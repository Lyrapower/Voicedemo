#!/usr/bin/env bash
# DISABLED 2026-07-23 — crypto paper CC CLI removed.
echo "paper-crypto-cli install disabled 2026-07-23" >&2
exit 0
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="${ROOT}/scripts/aether/launchd/com.demo.aether.paper-crypto-cli.plist"
DEST="${HOME}/Library/LaunchAgents/com.demo.aether.paper-crypto-cli.plist"
DOMAIN="gui/$(id -u)"
LABEL="com.demo.aether.paper-crypto-cli"
mkdir -p "${HOME}/Library/Logs/demo-aether"
chmod +x "${ROOT}/scripts/start_paper_crypto_cli_gated.sh"
SSL_CERT="$(python3 -m certifi 2>/dev/null || "${ROOT}/aether_nexus/.venv/bin/python" -m certifi 2>/dev/null || true)"
sed -e "s|__HOME__|${HOME}|g" -e "s|__DEMO_ROOT__|${ROOT}|g" -e "s|__SSL_CERT_FILE__|${SSL_CERT}|g" "${SRC}" >"${DEST}"
launchctl bootout "${DOMAIN}" "${DEST}" 2>/dev/null || true
sleep 1
launchctl bootstrap "${DOMAIN}" "${DEST}"
launchctl enable "${DOMAIN}/${LABEL}"
launchctl kickstart "${DOMAIN}/${LABEL}" || true
echo "OK — crypto paper CC CLI (sonnet-4.6 A/B lane) @ 09:10"
