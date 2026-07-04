#!/usr/bin/env bash
# Clear crashed error turns in Echo Nodes Interface chat; keep system prompt.
set -euo pipefail

CONV="${1:-$HOME/.lmstudio/conversations/17797865158101.conversation.json}"
CTX="${2:-8192}"

python3 - "$CONV" "$CTX" <<'PY'
import json, sys, time

path, ctx = sys.argv[1:3]
ctx = int(ctx)
now = int(time.time() * 1000)

with open(path, encoding="utf-8") as f:
    conv = json.load(f)

conv["messages"] = []
conv["tokenCount"] = 0
conv["userLastMessagedAt"] = now
conv["assistantLastMessagedAt"] = now

model = conv.get("lastUsedModel") or {}
fields = model.setdefault("instanceLoadTimeConfig", {}).setdefault("fields", [])
for field in fields:
    if field.get("key") == "llm.load.contextLength":
        field["value"] = ctx
        break
else:
    fields.append({"key": "llm.load.contextLength", "value": ctx})

notes = [n for n in conv.get("notes", []) if not str(n).startswith("CONTEXT_BUDGET:")]
notes.append(f"CONTEXT_BUDGET: {ctx} tokens (16GB stability)")
conv["notes"] = notes

with open(path, "w", encoding="utf-8") as f:
    json.dump(conv, f, ensure_ascii=False, indent=2)
    f.write("\n")
print(f"Reset messages in {path}; context={ctx}")
PY

echo "In LM Studio: Unload 35B → Load again with Context 8192 → send a short test message."
