#!/bin/bash
# Install macOS launchd job: every Sunday 10:00, OCR last week's screenshots.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PLIST_SRC="${ROOT}/scripts/ocr_text_inbox/com.ocr_text_inbox.weekly.plist"
PLIST_DST="${HOME}/Library/LaunchAgents/com.ocr_text_inbox.weekly.plist"
RUN_SH="${ROOT}/scripts/ocr_text_inbox/run_weekly_sync.sh"

chmod +x "${RUN_SH}"
mkdir -p "${HOME}/Library/LaunchAgents"

sed -e "s|__DEMO_ROOT__|${ROOT}|g" -e "s|__HOME__|${HOME}|g" "${PLIST_SRC}" > "${PLIST_DST}"

launchctl bootout "gui/$(id -u)/com.ocr_text_inbox.weekly" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST_DST}"
launchctl enable "gui/$(id -u)/com.ocr_text_inbox.weekly"

echo "Installed: ${PLIST_DST}"
echo "Runs: Sunday 10:00 — previous week's screenshots → OCR_Text_Inbox"
echo "Logs: ~/Desktop/OCR_Text_Inbox/weekly_sync.log"
echo "Test now: bash ${RUN_SH}"
