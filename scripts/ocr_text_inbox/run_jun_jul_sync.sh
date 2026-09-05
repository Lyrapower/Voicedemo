#!/bin/bash
# Sync June + July 2026 screenshots into OCR_Text_Inbox (Terminal.app only).
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT="$(pwd)"
VENV="${ROOT}/.venv_ocr_inbox"
INBOX="${HOME}/Desktop/OCR_Text_Inbox"
LOG="${INBOX}/jun_jul_sync.log"
mkdir -p "$INBOX"
echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) jun_jul_sync boot ===" >> "$LOG"

if [[ ! -d "$VENV" ]]; then
  python3 -m venv "$VENV"
fi
"${VENV}/bin/pip" install -q -U pip ocrmac pillow pytesseract pyobjc-framework-Photos >> "$LOG" 2>&1
export PYTHONPATH="${ROOT}"
export OCR_SKIP_IMAGE_SCREENSHOTS="${OCR_SKIP_IMAGE_SCREENSHOTS:-1}"

{
  echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) jun_jul_sync start ==="
  "${VENV}/bin/python" scripts/ocr_text_inbox/weekly_sync.py --month 2026-06
  "${VENV}/bin/python" scripts/ocr_text_inbox/weekly_sync.py --month 2026-07
  echo "=== full ocr_index.json rebuild (all months) ==="
  "${VENV}/bin/python" scripts/ocr_text_inbox/build_monthly_auto.py
  echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) jun_jul_sync DONE ==="
} 2>&1 | tee -a "$LOG"

touch "${INBOX}/.jun_jul_sync_done"
