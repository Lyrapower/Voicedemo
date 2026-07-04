#!/bin/bash
# Re-OCR garbled .md for 2025-09 .. 2026-05 (skip 2025-08 and already-good Chinese), then rebuild monthly books.
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT="$(pwd)"
VENV="${ROOT}/.venv_ocr_inbox"
INBOX="${HOME}/Desktop/OCR_Text_Inbox"
LOG="${INBOX}/mojibake_fix_progress.txt"

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

echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) MOJIBAKE FIX 2025-09 .. 2026-05 ===" | tee -a "${LOG}"
python scripts/ocr_text_inbox/restore_prioritized.py --mojibake-rebuild 2>&1 | tee -a "${LOG}"
echo "=== DONE $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee -a "${LOG}"
