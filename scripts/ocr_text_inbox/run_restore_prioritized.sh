#!/bin/bash
# Stop full re-OCR if running, then restore missing + fix mojibake + rebuild monthly books.
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT="$(pwd)"
VENV="$ROOT/.venv_ocr_inbox"
INBOX="$HOME/Desktop/OCR_Text_Inbox"

pkill -f "rerun_chinese_ocr.py" 2>/dev/null || true
sleep 1

if [[ ! -d "$VENV" ]]; then
  python3 -m venv "$VENV"
fi
# shellcheck source=/dev/null
source "$VENV/bin/activate"
pip install -q ocrmac pillow pyobjc-framework-Photos 2>/dev/null || pip install -q ocrmac pillow pyobjc-framework-Photos

echo "=== Audit + restore missing + fix mojibake + rebuild ===" | tee -a "$INBOX/restore_prioritized_progress.txt"
python scripts/ocr_text_inbox/restore_prioritized.py 2>&1 | tee -a "$INBOX/restore_prioritized_progress.txt"
echo "Done. See $INBOX/garbage_restore_audit.json"
