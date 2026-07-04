#!/usr/bin/env bash
# LM Studio Aster tab: config/aster.toml → prediction JSON; system_prompt field → systemPrompt only.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export ROOT
export PYTHONPATH="${ROOT}:${ROOT}/repo${PYTHONPATH:+:${PYTHONPATH}}"

python3 <<'PY'
import json, os, sqlite3, time
from pathlib import Path

from models.aster_config import (
    budget_section,
    database_path,
    gateway_endpoint,
    lm_studio_api_model,
    lm_studio_context_length,
    lm_studio_gateway_plugin,
    lm_studio_max_reasoning_tokens,
    lm_studio_max_tokens,
    lm_studio_repeat_penalty,
    lm_studio_tab_system_prompt,
    lm_studio_temperature,
    lm_studio_virtual_model_id,
    section,
)

ROOT = Path(os.environ["ROOT"])
ls = section("lm_studio")
archived = [str(x) for x in ls.get("archived_conversation_ids", [])]
conv_id = str(ls["conversation_id"])
name = str(ls.get("chat_name", "Aster"))
api_id = lm_studio_api_model()
ctx = lm_studio_context_length()
temp = lm_studio_temperature()
max_tok = lm_studio_max_tokens()
repeat = lm_studio_repeat_penalty()
budget = budget_section()
thinking_cap = lm_studio_max_reasoning_tokens()
system_prompt = lm_studio_tab_system_prompt()
gateway_plugin = lm_studio_gateway_plugin()
aster_model = lm_studio_virtual_model_id()
gateway_base = str(ls.get("gateway_api_base") or f"{gateway_endpoint()}/v1")
clear_history = os.environ.get("ASTER_DEPLOY_CLEAR", "") in ("1", "true", "yes")
enable_gateway_plugin = os.environ.get("ASTER_DEPLOY_GATEWAY_PLUGIN", "1") in ("1", "true", "yes")

PREDICTION_FIELDS = [
    {"key": "llm.prediction.systemPrompt", "value": system_prompt},
    {"key": "llm.prediction.temperature", "value": temp},
    {
        "key": "llm.prediction.maxPredictedTokens",
        "value": {"checked": True, "value": max_tok},
    },
    {
        "key": "llm.prediction.repeatPenalty",
        "value": {"checked": True, "value": repeat},
    },
    {
        "key": "llm.prediction.topPSampling",
        "value": {"checked": True, "value": 0.9},
    },
    {"key": "llm.prediction.topKSampling", "value": 40},
    {
        "key": "ext.virtualModel.customField.qwen.qwen3.59b.enableThinking",
        "value": False,
    },
]
if thinking_cap is not None:
    PREDICTION_FIELDS.append(
        {
            "key": "llm.prediction.maxReasoningTokens",
            "value": {"checked": True, "value": int(thinking_cap)},
        }
    )

db_path = database_path()
db_path.parent.mkdir(parents=True, exist_ok=True)
con = sqlite3.connect(db_path)
con.executescript("""
CREATE TABLE IF NOT EXISTS state (
   session_id TEXT NOT NULL,
   timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
   source TEXT DEFAULT 'lyra',
   channel TEXT,
   content TEXT,
   embedding_content BLOB,
   embedding_emotional BLOB,
   PRIMARY KEY (session_id, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_session ON state(session_id);
CREATE INDEX IF NOT EXISTS idx_timestamp ON state(timestamp);
""")
con.commit()
con.close()

conv_dir = Path.home() / ".lmstudio/conversations"

def patch(cid: str, tab_name: str, prompt: str, substrate_model: str, active_model: str):
    path = conv_dir / f"{cid}.conversation.json"
    if not path.is_file():
        raise SystemExit(f"Missing {path}")
    c = json.loads(path.read_text(encoding="utf-8"))
    c["name"] = tab_name
    c["systemPrompt"] = prompt
    if clear_history:
        c["messages"] = []
        c["tokenCount"] = 0
    c["usePerChatPredictionConfig"] = True
    c["perChatPredictionConfig"] = {"fields": PREDICTION_FIELDS}
    if enable_gateway_plugin:
        c["plugins"] = [gateway_plugin]
        c["tokenSourceIdentifier"] = {"type": "generator", "pluginIdentifier": gateway_plugin}
        c["lastUsedTokenSource"] = {"type": "generator", "pluginIdentifier": gateway_plugin}
    c["notes"] = [
        f"active={'gateway' if enable_gateway_plugin else 'direct'} model={active_model}",
        f"gateway={gateway_base}",
        f"substrate=:1234 {substrate_model}",
        f"temp={temp} max_tokens={max_tok} thinking_cap={thinking_cap}",
        "model picker → demo/aster (generator; lms dev must run)",
        "lm_studio_tab_only",
    ]
    now = int(time.time() * 1000)
    c["userLastMessagedAt"] = now
    c["assistantLastMessagedAt"] = now
    c["lastUsedModel"] = {
        "identifier": active_model,
        "indexedModelIdentifier": active_model,
        "instanceLoadTimeConfig": {"fields": []},
        "instanceOperationTimeConfig": {"fields": []},
    }
    path.write_text(json.dumps(c, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"OK  '{tab_name}' active_model={active_model} substrate={substrate_model} prompt={len(prompt)}c "
        f"max_tokens={max_tok} (chat budget) repeat={repeat} thinking_cap={budget.get('thinking_cap')}"
        + (" history_cleared" if clear_history else "")
    )

patch(
    conv_id,
    name,
    system_prompt,
    api_id,
    aster_model if enable_gateway_plugin else api_id,
)

plugin_prompt_path = ROOT / "lmstudio-plugins" / "aster-grid-gateway" / ".aster_system_prompt"
plugin_prompt_path.write_text(system_prompt + "\n", encoding="utf-8")
print(f"OK  plugin system prompt → {plugin_prompt_path} ({len(system_prompt)}c)")

# Qwen 9B default load/predict config (direct :1234 path)
qwen_cfg = Path.home() / ".lmstudio/.internal/user-concrete-model-default-config/qwen/qwen3.5-9b.json"
if qwen_cfg.is_file():
    qc = json.loads(qwen_cfg.read_text(encoding="utf-8"))
    op_fields = {f["key"]: f for f in (qc.get("operation") or {}).get("fields", [])}
    op_fields["llm.prediction.temperature"] = {"key": "llm.prediction.temperature", "value": temp}
    op_fields["llm.prediction.systemPrompt"] = {
        "key": "llm.prediction.systemPrompt",
        "value": system_prompt,
    }
    op_fields["llm.prediction.maxPredictedTokens"] = {
        "key": "llm.prediction.maxPredictedTokens",
        "value": {"checked": True, "value": max_tok},
    }
    op_fields["ext.virtualModel.customField.qwen.qwen3.59b.enableThinking"] = {
        "key": "ext.virtualModel.customField.qwen.qwen3.59b.enableThinking",
        "value": False,
    }
    if thinking_cap is not None:
        op_fields["llm.prediction.maxReasoningTokens"] = {
            "key": "llm.prediction.maxReasoningTokens",
            "value": {"checked": True, "value": int(thinking_cap)},
        }
    qc["operation"] = {"fields": list(op_fields.values())}
    load_fields = {f["key"]: f for f in (qc.get("load") or {}).get("fields", [])}
    load_fields["llm.load.contextLength"] = {"key": "llm.load.contextLength", "value": ctx}
    qc["load"] = {"fields": list(load_fields.values())}
    qwen_cfg.write_text(json.dumps(qc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OK  qwen default config temp={temp} max_tokens={max_tok} thinking_cap={thinking_cap}")

for aid in archived:
    p = conv_dir / f"{aid}.conversation.json"
    if p.is_file():
        c = json.loads(p.read_text(encoding="utf-8"))
        c["name"] = "[archived]"
        c["systemPrompt"] = ""
        p.write_text(json.dumps(c, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print("Done. LM Studio Aster tab synced from config/aster.toml — reload tab or send a new message.")

# self-check
import tomllib
from models.aster_config import build_lm_studio_system_prompt

want_prompt = build_lm_studio_system_prompt()
path = conv_dir / f"{conv_id}.conversation.json"
c = json.loads(path.read_text(encoding="utf-8"))
sp = c.get("systemPrompt", "")
fields = {f["key"]: f.get("value") for f in c.get("perChatPredictionConfig", {}).get("fields", [])}
toml_cfg = tomllib.loads((ROOT / "config" / "aster.toml").read_text("utf-8"))
budget_cfg = toml_cfg.get("budget") or {}
ls_cfg = toml_cfg.get("lm_studio") or {}
errors = []
if sp != want_prompt:
    errors.append("systemPrompt != build_lm_studio_system_prompt()")
if not sp.strip():
    errors.append("systemPrompt empty — expected Aster chat identity")
if fields.get("llm.prediction.systemPrompt") != sp:
    errors.append("perChatPredictionConfig out of sync")
mpt = fields.get("llm.prediction.maxPredictedTokens")
want = int(budget_cfg.get("chat_max_tokens", 400))
if not (isinstance(mpt, dict) and mpt.get("checked") and mpt.get("value") == want):
    errors.append(f"maxPredictedTokens not checked/{want}: {mpt!r}")
if fields.get("llm.prediction.temperature") != temp:
    errors.append(f"temperature not {temp}: {fields.get('llm.prediction.temperature')!r}")
want_model = aster_model if enable_gateway_plugin else ls_cfg["api_model_id"]
if c.get("lastUsedModel", {}).get("identifier") != want_model:
    errors.append(f"model id mismatch (want {want_model!r})")
if enable_gateway_plugin and gateway_plugin not in (c.get("plugins") or []):
    errors.append(f"gateway plugin {gateway_plugin!r} not in conversation.plugins")
if errors:
    raise SystemExit("VERIFY FAILED:\n  " + "\n  ".join(errors))
print("VERIFY OK")
print("--- systemPrompt ---")
print(sp)
PY
