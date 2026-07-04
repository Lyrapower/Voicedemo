#!/usr/bin/env bash
# Remove Qwen3.6 35B from 2TB + LM Studio metadata (keeps qwen3.5-9b).
set -euo pipefail

WEIGHTS_2TB="/Volumes/2TB/lmstudio/models/unsloth/qwen3.6-35b-a3b-ud-mlx-3bit"
HUB="$HOME/.lmstudio/hub/models/unsloth/qwen3.6-35b-a3b-mlx-3bit"
LM_UNSLOTH="$HOME/.lmstudio/models/unsloth"
MODEL_DATA="$HOME/.lmstudio/.internal/model-data.json"
NEW_MODEL="${NEW_MODEL:-qwen/qwen3.5-9b}"
NEW_CTX="${NEW_CTX:-8192}"

echo "=== Remove 35B + point chats to $NEW_MODEL ==="

lms unload unsloth/qwen3.6-35b-a3b-mlx-3bit 2>/dev/null || true
lms unload "unsloth/qwen3.6-35b-a3b-mlx-3bit" 2>/dev/null || true

if [[ -d "$WEIGHTS_2TB" ]]; then
  echo "Deleting 2TB weights (~16GB): $WEIGHTS_2TB"
  rm -rf "$WEIGHTS_2TB"
else
  echo "Skip 2TB weights (not found): $WEIGHTS_2TB"
fi

rm -rf "$HUB"
echo "Removed hub card: $HUB"

rm -f "$LM_UNSLOTH/.qwen3.6-35b-a3b-ud-mlx-3bit" "$LM_UNSLOTH/qwen3.6-35b-a3b-ud-mlx-3bit" 2>/dev/null || true
rmdir "$LM_UNSLOTH" 2>/dev/null || true

python3 - "$MODEL_DATA" <<'PY'
import json, sys
path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    data = json.load(f)
pairs = data["json"]
drop = []
keep = []
for key, val in pairs:
    k = key.lower()
    if "35b" in k or "qwen3.6-35" in k or "35b-a3b" in k:
        drop.append(key)
    else:
        keep.append([key, val])
data["json"] = keep
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False)
    f.write("\n")
print(f"model-data.json: removed {len(drop)} keys")
for k in drop:
    print(f"  - {k}")
PY

for conv in "$HOME/.lmstudio/conversations/"1779786515810*.conversation.json; do
  [[ -f "$conv" ]] || continue
  python3 - "$conv" "$NEW_MODEL" "$NEW_CTX" <<'PY'
import json, sys, time
path, model, ctx = sys.argv[1:4]
ctx = int(ctx)
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
c["notes"] = [
    n for n in c.get("notes", [])
    if not str(n).startswith("CONTEXT_BUDGET:")
] + [f"MODEL: {model}", f"CONTEXT_BUDGET: {ctx}"]
c["userLastMessagedAt"] = c.get("userLastMessagedAt") or now
c["assistantLastMessagedAt"] = c.get("assistantLastMessagedAt") or now
with open(path, "w", encoding="utf-8") as f:
    json.dump(c, f, ensure_ascii=False, indent=2)
    f.write("\n")
print(f"Updated {path}")
PY
done

echo ""
echo "Done. Verify: lms ls"
lms ls 2>&1 || true
