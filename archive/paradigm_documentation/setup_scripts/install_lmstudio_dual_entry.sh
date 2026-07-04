#!/usr/bin/env bash
# Create two NEW isolated LM Studio chats (Entry A + Entry B). Prefer existing IDs via apply_lmstudio_dual_14b.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENI_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LM_CONV="$HOME/.lmstudio/conversations"
CONTEXT_TOKENS=8192
MODEL_ID="${MODEL_ID:-$(python3 -c "import json;print(json.load(open('$ENI_ROOT/config/entry_lm_model.json'))['lms_load_name'])")}"
TS_MS="$(python3 -c 'import time; print(int(time.time()*1000))')"
ECHO_ID="${TS_MS}1.conversation.json"
QWEN_ID="${TS_MS}2.conversation.json"

python3 "$ENI_ROOT/setup/build_echo_system_prompt.py"
ECHO_PROMPT="$(cat "$ENI_ROOT/prompts/echo_nodes_system.txt")"
COMPILE_PROMPT="$(cat "$ENI_ROOT/prompts/entry_b_compile_system.txt")"
mkdir -p "$LM_CONV" "$ENI_ROOT/incoming/echo_nodes" "$ENI_ROOT/incoming/qwen_native"

python3 - "$LM_CONV/$ECHO_ID" "$LM_CONV/$QWEN_ID" "$ECHO_PROMPT" "$COMPILE_PROMPT" "$CONTEXT_TOKENS" "$MODEL_ID" "$ECHO_ID" "$QWEN_ID" <<'PY'
import json, sys, time

echo_path, qwen_path, echo_prompt, compile_prompt, ctx, model, echo_file, qwen_file = sys.argv[1:9]
now = int(time.time() * 1000)

def make_conv(name, system_prompt, conv_file, workdir_name, plugins):
    return {
        "name": name,
        "pinned": True,
        "createdAt": now,
        "preset": "",
        "tokenCount": 0,
        "userLastMessagedAt": now,
        "assistantLastMessagedAt": now,
        "systemPrompt": system_prompt,
        "messages": [],
        "usePerChatPredictionConfig": True,
        "perChatPredictionConfig": {
            "fields": [
                {
                    "key": "llm.prediction.systemPrompt",
                    "value": system_prompt,
                }
            ]
        },
        "clientInput": "",
        "clientInputFiles": [],
        "userFilesSizeBytes": 0,
        "lastUsedModel": {
            "indexedModelIdentifier": model,
            "identifier": model,
            "instanceLoadTimeConfig": {
                "fields": [
                    {"key": "llm.load.contextLength", "value": int(ctx)},
                    {"key": "llm.load.useUnifiedKvCache", "value": False},
                    {"key": "llm.load.offloadKVCacheToGpu", "value": True},
                    {"key": "llm.load.llama.keepModelInMemory", "value": True},
                ]
            },
            "instanceOperationTimeConfig": {"fields": []},
        },
        "notes": [
            "ENTRY_ISOLATION: separate tab; NOT merged.",
            f"MODEL: {model}",
            f"CONTEXT_BUDGET: {ctx}",
        ],
        "plugins": plugins,
        "pluginConfigs": {},
        "disabledPluginTools": [],
        "looseFiles": [],
        "workingDirectoryName": workdir_name.replace(".conversation.json", ""),
    }

with open(echo_path, "w", encoding="utf-8") as f:
    json.dump(make_conv("Echo Nodes Interface", echo_prompt, echo_file, echo_file, []), f, ensure_ascii=False, indent=2)
    f.write("\n")

with open(qwen_path, "w", encoding="utf-8") as f:
    json.dump(
        make_conv("Compile Layer（Entry B）", compile_prompt, qwen_file, qwen_file, []),
        f,
        ensure_ascii=False,
        indent=2,
    )
    f.write("\n")

print(echo_path)
print(qwen_path)
PY

echo "Created:"
echo "  $LM_CONV/$ECHO_ID"
echo "  $LM_CONV/$QWEN_ID"
echo ""
echo "In LM Studio: Chat → drag each tab to split view (50/50)."
echo "Then run: $ENI_ROOT/setup/apply_lmstudio_dual_entry.sh (if using fixed conv IDs 17797865158101/02)"
echo "Load model: $MODEL_ID · context $CONTEXT_TOKENS"
echo "Entry A files: $ENI_ROOT/incoming/echo_nodes/"
