#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT="$(pwd)"
VENV="${ROOT}/.venv_ocr_inbox"
if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi
# shellcheck source=/dev/null
source "${VENV}/bin/activate"
pip install -q -U pip ocrmac pillow pytesseract
if command -v brew >/dev/null 2>&1; then
  brew list tesseract >/dev/null 2>&1 || brew install tesseract tesseract-lang
fi
export PYTHONPATH="${ROOT}"
echo "Starting Chinese-capable re-OCR of all screenshots Aug 2025 - May 2026..."
python scripts/ocr_text_inbox/rerun_chinese_ocr.py 2>&1 | tee -a "$HOME/Desktop/OCR_Text_Inbox/rerun_chinese_progress.txt"
