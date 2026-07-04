#!/bin/bash
# Round 2 OCR fix: 2025-08 .. 2026-05 legacy/garbled notes. Terminal.app + Photos required.
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
export OCR_SKIP_IMAGE_SCREENSHOTS="${OCR_SKIP_IMAGE_SCREENSHOTS:-1}"

echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) ROUND 2 OCR (2025-08 .. 2026-05, skip image-heavy) ===" | tee -a "${INBOX}/round2_ocr_fix_progress.txt"
python scripts/ocr_text_inbox/round2_ocr_fix.py 2>&1 | tee -a "${INBOX}/round2_ocr_fix_progress.txt"
echo "=== DONE $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee -a "${INBOX}/round2_ocr_fix_progress.txt"
