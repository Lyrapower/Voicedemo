#!/usr/bin/env bash
# Lower 35B context for faster prefill (both entry A + B). Reversible via install script.
set -euo pipefail

CONTEXT="${1:-32768}"
ECHO_ID="${ECHO_CONV_ID:-17797865158101}"
QWEN_ID="${QWEN_CONV_ID:-17797865158102}"
LM_CONV="$HOME/.lmstudio/conversations"

python3 - "$LM_CONV/${ECHO_ID}.conversation.json" "$LM_CONV/${QWEN_ID}.conversation.json" "$CONTEXT" <<'PY'
import json, sys

def patch(path: str, ctx: int) -> None:
    with open(path, encoding="utf-8") as f:
        conv = json.load(f)
    model = conv.get("lastUsedModel") or {}
    fields = model.setdefault("instanceLoadTimeConfig", {}).setdefault("fields", [])
    found = False
    for field in fields:
        if field.get("key") == "llm.load.contextLength":
            field["value"] = ctx
            found = True
            break
    if not found:
        fields.append({"key": "llm.load.contextLength", "value": ctx})
    notes = conv.setdefault("notes", [])
    note = f"CONTEXT_BUDGET: {ctx} tokens (speed profile)"
    conv["notes"] = [n for n in notes if not str(n).startswith("CONTEXT_BUDGET:")] + [note]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(conv, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"  {path} -> context {ctx}")

echo_path, qwen_path, ctx = sys.argv[1:4]
ctx = int(ctx)
patch(echo_path, ctx)
patch(qwen_path, ctx)
print(f"\nDone. Unload/reload model in LM Studio, then chat.")
print(f"To use another size: $0 65536")
PY
