#!/usr/bin/env python3
"""Verify Aster dual-path fix on user chain — Fable rule: evidence before user retest."""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GS = ROOT / "grid-sovereign-runtime"
PROOF = GS / "traces" / "proof"
OUT = PROOF / "USER_CHAIN_FIX_ACCEPTANCE.json"
GATEWAY = "http://127.0.0.1:8501"
LM = "http://127.0.0.1:1234/v1"
PROMPT = "摘星人买菜不看价签,看菜上的露水还在不在。你说露水是什么?"


def _post(url: str, body: dict, *, timeout: float = 180.0) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _lm_runtime() -> dict:
    sys.path.insert(0, str(ROOT))
    from models.aster_config import lm_studio_temperature, section

    conv = Path.home() / f".lmstudio/conversations/{section('lm_studio')['conversation_id']}.conversation.json"
    data = json.loads(conv.read_text(encoding="utf-8"))
    fields = {f["key"]: f.get("value") for f in (data.get("perChatPredictionConfig") or {}).get("fields", [])}
    mpt = fields.get("llm.prediction.maxPredictedTokens") or {}
    mrt = fields.get("llm.prediction.maxReasoningTokens") or {}
    return {
        "conversation": str(conv),
        "temperature": fields.get("llm.prediction.temperature"),
        "toml_temperature": lm_studio_temperature(),
        "max_predicted_tokens": mpt.get("value") if isinstance(mpt, dict) else mpt,
        "max_reasoning_tokens": mrt.get("value") if isinstance(mrt, dict) else mrt,
        "enable_thinking": fields.get("ext.virtualModel.customField.qwen.qwen3.59b.enableThinking"),
        "message_count": len(data.get("messages") or []),
        "plugins": data.get("plugins") or [],
        "notes": data.get("notes") or [],
    }


def main() -> int:
    PROOF.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    gw = _post(
        f"{GATEWAY}/v1/chat/completions",
        {"messages": [{"role": "user", "content": PROMPT}], "max_tokens": 400, "temperature": 0.7},
    )
    gw_text = (gw.get("choices") or [{}])[0].get("message", {}).get("content") or gw.get("response") or ""

    lm = _post(
        f"{LM}/chat/completions",
        {
            "model": "demo/aster",
            "messages": [
                {"role": "user", "content": PROMPT},
                {"role": "assistant", "content": " \n"},
            ],
            "max_tokens": 400,
            "temperature": 0.7,
            "enable_thinking": False,
            "max_reasoning_tokens": 128,
        },
    )
    lm_ch = (lm.get("choices") or [{}])[0]
    lm_text = str(lm_ch.get("message", {}).get("content") or "")
    lm_usage = lm.get("usage") or {}
    lm_det = lm_usage.get("completion_tokens_details") or {}

    runtime = _lm_runtime()
    plugin_dest = Path.home() / ".lmstudio/extensions/plugins/demo/aster"
    plugin_built = (plugin_dest / ".lmstudio/production.js").is_file()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "canonical_prompt": PROMPT,
        "gateway_path": {
            "served_by": gw.get("served_by"),
            "response_len": len(gw_text),
            "truncated": gw.get("truncated"),
            "finish_reason": (gw.get("choices") or [{}])[0].get("finish_reason"),
            "pass": bool(gw.get("served_by")) and len(gw_text) >= 20 and not gw.get("truncated"),
        },
        "direct_path": {
            "served_by": lm.get("served_by"),
            "response_len": len(lm_text.strip()),
            "reasoning_tokens": lm_det.get("reasoning_tokens"),
            "completion_tokens": lm_usage.get("completion_tokens"),
            "finish_reason": lm_ch.get("finish_reason"),
            "pass": lm.get("served_by") is None and len(lm_text.strip()) >= 40 and int(lm_det.get("reasoning_tokens") or 0) < 200,
        },
        "lm_studio_runtime": runtime,
        "gateway_plugin": {
            "id": "demo/aster",
            "installed": plugin_dest.is_symlink() or plugin_dest.is_dir(),
            "built": plugin_built,
            "in_conversation_plugins": "demo/aster" in (runtime.get("plugins") or []),
        },
        "elapsed_s": round(time.time() - t0, 2),
    }
    report["overall"] = (
        "PASS"
        if report["gateway_path"]["pass"] and report["direct_path"]["pass"] and runtime.get("temperature") == 0.7
        else "FAIL"
    )

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nWrote {OUT}")
    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
