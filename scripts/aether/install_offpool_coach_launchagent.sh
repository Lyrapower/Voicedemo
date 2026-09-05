#!/usr/bin/env bash
# DISABLED 2026-07-23 — offpool Fable coach removed.
echo "offpool-coach install disabled 2026-07-23" >&2
exit 0
# DISABLED 2026-07-20 — Fable offpool-coach channel removed
echo "offpool-coach terminated 2026-07-20 — see vault/04-决策Decisions/" >&2
exit 0
# Install off-pool Fable coach LaunchAgent — PREMARKET 06:20 US/Pacific, weekdays.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="${ROOT}/scripts/aether/launchd/com.demo.aether.offpool-coach.plist"
DEST="${HOME}/Library/LaunchAgents/com.demo.aether.offpool-coach.plist"
LOG="${HOME}/Library/Logs/demo-aether"
DOMAIN="gui/$(id -u)"
LABEL="com.demo.aether.offpool-coach"

mkdir -p "${LOG}"
chmod +x "${ROOT}/scripts/start_offpool_coach_gated.sh"

SSL_CERT="$(python3 -m certifi 2>/dev/null || "${ROOT}/aether_nexus/.venv/bin/python" -m certifi 2>/dev/null || true)"
sed \
  -e "s|__HOME__|${HOME}|g" \
  -e "s|__DEMO_ROOT__|${ROOT}|g" \
  -e "s|__SSL_CERT_FILE__|${SSL_CERT}|g" \
  "${SRC}" >"${DEST}"

if launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
  launchctl bootout "${DOMAIN}" "${DEST}" 2>/dev/null || true
  sleep 1
fi

pkill -f "offpool_coach_daemon.py --loop" 2>/dev/null || true
sleep 1

launchctl bootstrap "${DOMAIN}" "${DEST}"
launchctl enable "${DOMAIN}/${LABEL}"
launchctl kickstart "${DOMAIN}/${LABEL}" || true
sleep 2

state="$(launchctl print "${DOMAIN}/${LABEL}" 2>/dev/null | grep "state = " | head -1 | sed 's/.*= //' || echo missing)"
pid="$(pgrep -f 'offpool_coach_daemon.py' | head -1 || true)"

echo "offpool-coach agent state=${state} pid=${pid:-none}"
if [[ "${state}" != "running" || -z "${pid}" ]]; then
  echo "FAIL — see ${LOG}/offpool-coach.err.log"
  tail -20 "${LOG}/offpool-coach.err.log" 2>/dev/null || true
  exit 1
fi

echo "OK — offpool Fable coach PREMARKET ${PREMARKET_WINDOW_PST:-06:20} + EXECUTION ${EXEC_WINDOW_PST:-07:15} US/Pacific (trial from ${OFFPOOL_COACH_TRIAL_START:-2026-07-17})"
