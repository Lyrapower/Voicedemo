#!/bin/bash
# Restore deleted Chinese OCR notes (2025-08-01 .. 2026-05-20) + rebuild monthly books.
# Does NOT re-OCR all screenshots. Does NOT touch pre-Aug 2025. Run in Terminal.app only.
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT="$(pwd)"
VENV="${ROOT}/.venv_ocr_inbox"
INBOX="${HOME}/Desktop/OCR_Text_Inbox"

if [[ ! -d "$VENV" ]]; then
  python3 -m venv "$VENV"
fi
# shellcheck source=/dev/null
source "${VENV}/bin/activate"
pip install -q -U pip ocrmac pillow pytesseract pyobjc-framework-Photos
if command -v brew >/dev/null 2>&1; then
  brew list tesseract >/dev/null 2>&1 || brew install tesseract tesseract-lang
fi
export PYTHONPATH="${ROOT}"

echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) RESTORE DELETED CHINESE ONLY (2025-08-01 .. 2026-05-20) ===" | tee -a "${INBOX}/ocr_fix_progress.txt"

python scripts/ocr_text_inbox/restore_prioritized.py --missing-rebuild 2>&1 | tee -a "${INBOX}/restore_prioritized_progress.txt"

echo "=== DONE $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee -a "${INBOX}/ocr_fix_progress.txt"
