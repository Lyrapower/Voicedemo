#!/usr/bin/env bash
# Install Qwen3.5-9B dense MLX 4bit for Echo Nodes + compile layer (16GB Mac).
set -euo pipefail

ENI_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODEL_URL="${MODEL_URL:-https://huggingface.co/mlx-community/Qwen3.5-9B-MLX-4bit}"
CTX="${CTX:-8192}"
ECHO_CONV="${ECHO_CONV:-17797865158101}"
QWEN_CONV="${QWEN_CONV:-17797865158102}"

echo "=== Install Echo/compile model: Qwen3.5-9B-MLX-4bit ==="
echo "URL: $MODEL_URL"
echo ""

if ! command -v lms >/dev/null 2>&1; then
  echo "ERROR: lms CLI not found. Install LM Studio and ensure ~/.lmstudio/bin is on PATH."
  exit 1
fi

lms unload unsloth/qwen3.6-35b-a3b-mlx-3bit 2>/dev/null || true

echo "Downloading (MLX)..."
lms get "$MODEL_URL" --mlx -y

echo ""
echo "Pointing LM Studio chats to downloaded model (by HF id)..."
LM_ID="mlx-community/Qwen3.5-9B-MLX-4bit"
export LM_ID CTX ECHO_CONV QWEN_CONV

for conv in "$HOME/.lmstudio/conversations/${ECHO_CONV}.conversation.json" \
            "$HOME/.lmstudio/conversations/${QWEN_CONV}.conversation.json"; do
  [[ -f "$conv" ]] || continue
  python3 - "$conv" <<'PY'
import json, os, sys, time
path = sys.argv[1]
model = os.environ["LM_ID"]
ctx = int(os.environ["CTX"])
now = int(time.time() * 1000)
with open(path, encoding="utf-8") as f:
    c = json.load(f)
c["lastUsedModel"] = {
    "identifier": model,
    "indexedModelIdentifier": model,
    "instanceLoadTimeConfig": {
        "fields": [
            {"key": "llm.load.contextLength", "value": ctx},
            {"key": "llm.load.useUnifiedKvCache", "value": False},
            {"key": "llm.load.offloadKVCacheToGpu", "value": True},
        ]
    },
    "instanceOperationTimeConfig": {"fields": []},
}
c["userLastMessagedAt"] = c.get("userLastMessagedAt") or now
c["assistantLastMessagedAt"] = c.get("assistantLastMessagedAt") or now
notes = [n for n in c.get("notes", []) if not str(n).startswith(("MODEL:", "CONTEXT_BUDGET:"))]
notes += [f"MODEL: {model}", f"CONTEXT_BUDGET: {ctx} (echo/compile mlx dense)"]
c["notes"] = notes
with open(path, "w", encoding="utf-8") as f:
    json.dump(c, f, ensure_ascii=False, indent=2)
    f.write("\n")
print("  updated", path)
PY
done

# Project config
python3 - <<PY
import json
from pathlib import Path
root = Path("$ENI_ROOT")
for rel in ["incoming/echo_nodes/config.json", "config/entry_split.json"]:
    p = root / rel
    data = json.loads(p.read_text())
    if "lm_studio" in data:
        data["lm_studio"]["model"] = "$LM_ID"
        data["lm_studio"]["context_tokens"] = $CTX
    if "model" in data:
        data["model"] = "$LM_ID"
    for e in data.get("entries", []):
        e["context_tokens"] = $CTX
    p.write_text(json.dumps(data, indent=2) + "\n")
    print("  config", p)
PY

echo ""
echo "Done. In LM Studio:"
echo "  1) Quit and reopen LM Studio"
echo "  2) Load: mlx-community/Qwen3.5-9B-MLX-4bit (or name shown in lms ls)"
echo "  3) Context: $CTX"
echo "  4) Open Echo Nodes Interface"
echo ""
lms ls 2>&1 | head -20
