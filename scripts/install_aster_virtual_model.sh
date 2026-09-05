#!/usr/bin/env bash
# Symlink/copy demo/aster virtual model.yaml into LM Studio hub (My Models picker).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/lmstudio-models/demo/aster"
DEST="$HOME/.lmstudio/hub/models/demo/aster"

if [[ ! -f "$SRC/model.yaml" ]]; then
  echo "FAIL: missing $SRC/model.yaml"
  exit 1
fi

mkdir -p "$DEST"
cp -f "$SRC/model.yaml" "$DEST/model.yaml"
export ROOT
PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}" python3 - <<'PY'
from pathlib import Path
import os
import sys

ROOT = Path(os.environ["ROOT"])
sys.path.insert(0, str(ROOT))
from models.aster_config import lm_studio_tab_system_prompt

dest = Path.home() / ".lmstudio/hub/models/demo/aster/model.yaml"
prompt = lm_studio_tab_system_prompt()
text = dest.read_text(encoding="utf-8")
marker = 'value: ""'
inject = "value: |-\n" + "\n".join("          " + line for line in prompt.splitlines())
if marker in text:
    dest.write_text(text.replace(marker, inject, 1), encoding="utf-8")
    print(f"OK  injected systemPrompt ({len(prompt)}c) into {dest}")
else:
    print(f"WARN: could not inject prompt into {dest} (marker missing)")
PY
echo "OK: virtual model demo/aster → $DEST"
