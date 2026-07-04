#!/bin/bash
# Weekly OCR sync — run in Terminal.app (Photos permission). Default: previous Mon–Sun.
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

echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) weekly_sync ===" | tee -a "${INBOX}/weekly_sync.log"
python scripts/ocr_text_inbox/weekly_sync.py --last-week "$@" 2>&1 | tee -a "${INBOX}/weekly_sync.log"
