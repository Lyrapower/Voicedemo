#!/usr/bin/env bash
# Refresh Aster Compile LM Studio chat only (never touches daily 9B tab).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
python3 "$ROOT/aster/setup/build_compile_system_prompt.py"
CONV_ID="${COMPILE_CONV_ID:-17797865158102}"
CONV_PATH="$HOME/.lmstudio/conversations/${CONV_ID}.conversation.json"
PROMPT_FILE="$ROOT/aster/prompts/compile_system.txt"
NAME="Aster Compile"

if [[ ! -f "$CONV_PATH" ]]; then
  echo "Missing conversation: $CONV_PATH"
  exit 1
fi
if [[ ! -s "$PROMPT_FILE" ]]; then
  echo "Empty prompt file: $PROMPT_FILE"
  exit 1
fi

PROMPT="$(cat "$PROMPT_FILE")"

python3 - "$CONV_PATH" "$PROMPT" "$NAME" <<'PY'
import json, sys

path, prompt, name = sys.argv[1:4]
with open(path, encoding="utf-8") as f:
    conv = json.load(f)

conv["name"] = name
conv["systemPrompt"] = prompt
now = conv.get("createdAt") or int(__import__("time").time() * 1000)
conv["userLastMessagedAt"] = conv.get("userLastMessagedAt") or now
conv["assistantLastMessagedAt"] = conv.get("assistantLastMessagedAt") or now

fields = conv.get("perChatPredictionConfig", {}).get("fields", [])
for field in fields:
    if field.get("key") == "llm.prediction.systemPrompt":
        field["value"] = prompt
        break
else:
    conv.setdefault("perChatPredictionConfig", {"fields": []})
    conv["perChatPredictionConfig"]["fields"].append(
        {"key": "llm.prediction.systemPrompt", "value": prompt}
    )

with open(path, "w", encoding="utf-8") as f:
    json.dump(conv, f, ensure_ascii=False, indent=2)
    f.write("\n")
print(f"Updated Aster Compile: {path} ({name})")
PY

MODEL_ID="$(python3 -c "import json;print(json.load(open('$ROOT/aster/config/local_models.json'))['compile']['lms_load_name'])")"
CTX="$(python3 -c "import json;print(json.load(open('$ROOT/aster/config/local_models.json'))['compile']['context_length'])")"

python3 - "$CONV_PATH" "$MODEL_ID" "$CTX" <<'PY'
import json, sys, time
from pathlib import Path

path = Path(sys.argv[1])
model, ctx = sys.argv[2:4]
c = json.loads(path.read_text(encoding="utf-8"))
c["lastUsedModel"] = {
    "identifier": model,
    "indexedModelIdentifier": model,
    "instanceLoadTimeConfig": {
        "fields": [
            {"key": "llm.load.contextLength", "value": int(ctx)},
            {"key": "llm.load.useUnifiedKvCache", "value": False},
            {"key": "llm.load.offloadKVCacheToGpu", "value": True},
        ]
    },
    "instanceOperationTimeConfig": {"fields": []},
}
notes = [n for n in c.get("notes", []) if not str(n).startswith(("MODEL:", "CONTEXT_BUDGET:", "CHANNEL:", "HTTP_PORT:"))]
notes += [
    "CHANNEL: aster_compile @ 8787",
    f"MODEL: {model}",
    f"CONTEXT_BUDGET: {ctx}",
    "HTTP_PORT: 8787",
]
c["notes"] = notes
path.write_text(json.dumps(c, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"  model={model} ctx={ctx}")
PY

echo "Aster Compile system prompt applied. Daily 9B tab unchanged."
