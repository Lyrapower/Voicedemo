#!/usr/bin/env bash
# Regenerate xcodeproj, ensure AppIcon exists, then run the same xcodebuild as acceptance.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# 1024x1024 placeholder AppIcon (ocean) — required for asset compile if Icon.png is missing
ICON="$ROOT/TripPackAI/Assets.xcassets/AppIcon.appiconset/Icon.png"
if [[ ! -f "$ICON" ]]; then
  echo "Recreating AppIcon/Icon.png (was missing)…"
  python3 - "$ICON" <<'PY'
import struct, zlib, sys
from pathlib import Path
path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
w, h, r, g, b, a = 1024, 1024, 14, 116, 144, 255
def chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
row = b"\x00" + bytes([r, g, b, a]) * w
raw = zlib.compress(row * h, 9)
ihdr = struct.pack(">2I5B", w, h, 8, 6, 0, 0, 0)
png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")
path.write_bytes(png)
print("Wrote", path)
PY
fi

echo "Clearing old DerivedData for this project…"
rm -rf "${HOME?}/Library/Developer/Xcode/DerivedData/TripPackAI-"* 2>/dev/null || true

echo "Regenerating TripPackAI.xcodeproj…"
python3 "$ROOT/tools/build_pbx.py"

echo "Running tools/xcodebuild_acceptance.sh…"
exec "$ROOT/tools/xcodebuild_acceptance.sh"
