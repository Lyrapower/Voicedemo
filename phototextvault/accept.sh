#!/usr/bin/env bash
# PhotoTextVault acceptance: venv, deps, unit tests, sample monthly export.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV="${ROOT}/.venv_phototextvault"
if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi
# shellcheck source=/dev/null
source "${VENV}/bin/activate"

pip install -q -U pip
pip install -q -r "${ROOT}/phototextvault/requirements.txt" pytest

export PYTHONPATH="${ROOT}"
pytest "${ROOT}/phototextvault/tests" -q

TMP="$(mktemp -d)"
SRC="${TMP}/PhotosExport"
OUT="${TMP}/PhotoTextVault"
mkdir -p "$SRC"

export PTV_SRC="$SRC"
python3 <<'PY'
from pathlib import Path
import os
from PIL import Image, ImageDraw

src_dir = Path(os.environ["PTV_SRC"])
for y, m, d, text in (
    (2025, 8, 10, "PTV_ACCEPT_AUG"),
    (2025, 9, 1, "PTV_ACCEPT_SEP"),
):
    name = f"Screenshot {y}-{m:02d}-{d:02d} at 12.00.00.png"
    img = Image.new("RGB", (320, 120), "white")
    dr = ImageDraw.Draw(img)
    dr.text((12, 40), text, fill="black")
    img.save(src_dir / name)

# Same calendar day + identical OCR as first August image → duplicate, logged only
img2 = Image.new("RGB", (320, 120), "white")
dr2 = ImageDraw.Draw(img2)
dr2.text((12, 40), "PTV_ACCEPT_AUG", fill="black")
img2.save(src_dir / "Screenshot 2025-08-10 at 13.00.00.png")
PY

python3 -m phototextvault.export \
  --source-folder "$SRC" \
  --start 2025-08-01 \
  --end 2026-04-23 \
  --monthly \
  --out-dir "$OUT"

MONTHLY=(
  "2025-08_to_2025-09.md"
  "2025-09_to_2025-10.md"
  "2025-10_to_2025-11.md"
  "2025-11_to_2025-12.md"
  "2025-12_to_2026-01.md"
  "2026-01_to_2026-02.md"
  "2026-02_to_2026-03.md"
  "2026-03_to_2026-04.md"
  "2026-04-01_to_2026-04-23.md"
)

for f in "${MONTHLY[@]}"; do
  test -f "${OUT}/${f}"
done
test -d "${OUT}/raw_text"
test -d "${OUT}/logs"

BAD='text_hash|screenshot_score|score_reasons|exif_camera|internal_path|source_path|ocr_sha256|width:|height:'
if grep -Eiq "$BAD" "${OUT}"/*.md 2>/dev/null; then
  echo "FAIL: forbidden metadata in main markdown"
  exit 1
fi

for f in "${MONTHLY[@]}"; do
  if ! grep -Eq '^## [0-9]{4}-[0-9]{2}-[0-9]{2}|No screenshots found for this date range' "${OUT}/${f}"; then
    echo "FAIL: ${f} missing day heading or empty-range message"
    exit 1
  fi
done

if ! grep -q "## 2025-08-10" "${OUT}/2025-08_to_2025-09.md"; then
  echo "FAIL: August screenshot day missing"
  exit 1
fi
if ! grep -q "## 2025-09-01" "${OUT}/2025-09_to_2025-10.md"; then
  echo "FAIL: September screenshot day missing"
  exit 1
fi
if grep -q "## 2025-09-01" "${OUT}/2025-08_to_2025-09.md"; then
  echo "FAIL: September content leaked into August file"
  exit 1
fi

if ! grep -q "duplicate_skipped" "${OUT}/logs/export.log"; then
  echo "FAIL: expected duplicate_skipped in logs"
  exit 1
fi

if ! grep -q "PTV_ACCEPT_AUG" "${OUT}/2025-08_to_2025-09.md"; then
  echo "FAIL: expected OCR marker in August monthly file"
  exit 1
fi
if ! grep -q "PTV_ACCEPT_SEP" "${OUT}/2025-09_to_2025-10.md"; then
  echo "FAIL: expected OCR marker in September monthly file"
  exit 1
fi

# Only one August screenshot body (duplicate dropped)
AUG_SHOTS="$(grep -c '^### Screenshot' "${OUT}/2025-08_to_2025-09.md" || true)"
if [ "${AUG_SHOTS}" != "1" ]; then
  echo "FAIL: expected exactly 1 screenshot section in August file, got ${AUG_SHOTS}"
  exit 1
fi

echo "ACCEPTANCE PASS"
echo "Monthly editable MD files created: YES"
echo "Date ranges respected: YES"
echo "No duplicate month overlap: YES"
echo "Debug metadata hidden: YES"
echo "Raw OCR preserved: YES"
