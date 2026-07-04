#!/usr/bin/env python3
"""P0: Aster tab single-request attribution + fingerprint evidence."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from models.aster_config import section  # noqa: E402

CONV_ID = str(section("lm_studio")["conversation_id"])
CONV_PATH = Path.home() / f".lmstudio/conversations/{CONV_ID}.conversation.json"
PLUGIN_SRC = ROOT / "lmstudio-plugins/aster-grid-gateway/src/index.ts"
OUT = ROOT / "grid-sovereign-runtime/traces/proof/aster_tab_fingerprint.json"
MATRIX = ROOT / "grid-sovereign-runtime/traces/proof/reproduction_matrix.json"

TEST_PROMPT = "链路指纹探测：一句话说明露水是什么。"
GATEWAY = "http://127.0.0.1:8501"
LM = "http://127.0.0.1:1234"


def _load_conv() -> dict:
    return json.loads(CONV_PATH.read_text(encoding="utf-8"))


def _ui_config_evidence(c: dict) -> dict:
    return {
        "conversation_path": str(CONV_PATH),
        "conversation_name": c.get("name"),
        "lastUsedModel": c.get("lastUsedModel"),
        "tokenSourceIdentifier": c.get("tokenSourceIdentifier"),
        "lastUsedTokenSource": c.get("lastUsedTokenSource"),
        "plugins": c.get("plugins"),
        "notes": c.get("notes"),
        "systemPrompt_chars": len(c.get("systemPrompt") or ""),
        "perChatPredictionConfig_keys": [
            f.get("key") for f in (c.get("perChatPredictionConfig") or {}).get("fields", [])
        ],
    }


def _plugin_target() -> dict:
    text = PLUGIN_SRC.read_text(encoding="utf-8") if PLUGIN_SRC.is_file() else ""
    gateway_line = next((ln.strip() for ln in text.splitlines() if "GATEWAY_URL" in ln), "")
    model_line = next((ln.strip() for ln in text.splitlines() if "MODEL" in ln and "process.env" in ln), "")
    return {
        "plugin_source": str(PLUGIN_SRC),
        "gateway_url_literal": gateway_line,
        "model_literal": model_line,
        "inferred_post_url": "http://127.0.0.1:8501/v1/chat/completions",
        "plugin_stream_mode": "stream: false (single fetch; LM Studio UI may still animate)",
    }


def _get_json(url: str, timeout: float = 5.0) -> tuple[int, dict | str, float]:
    t0 = time.time()
    try:
        r = httpx.get(url, timeout=timeout)
        elapsed = time.time() - t0
        try:
            return r.status_code, r.json(), elapsed
        except Exception:
            return r.status_code, r.text, elapsed
    except Exception as e:
        return 0, str(e), time.time() - t0


def _post_json(url: str, body: dict, timeout: float = 120.0) -> tuple[int, dict | str, float]:
    t0 = time.time()
    try:
        r = httpx.post(url, json=body, timeout=timeout)
        elapsed = time.time() - t0
        try:
            return r.status_code, r.json(), elapsed
        except Exception:
            return r.status_code, r.text, elapsed
    except Exception as e:
        return 0, str(e), time.time() - t0


def _stream_capture(url: str, body: dict, timeout: float = 120.0) -> dict:
    t0 = time.time()
    chunks: list[dict] = []
    raw_lines: list[str] = []
    with httpx.stream("POST", url, json=body, timeout=timeout) as r:
        for line in r.iter_lines():
            if not line:
                continue
            raw_lines.append(line)
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunks.append(json.loads(data))
            except json.JSONDecodeError:
                pass
    last = chunks[-1] if chunks else {}
    return {
        "chunk_count": len(chunks),
        "last_chunk": last,
        "served_by_in_last_chunk": last.get("served_by"),
        "route_id_in_last_chunk": last.get("route_id"),
        "finish_reason": (last.get("choices") or [{}])[0].get("finish_reason"),
        "elapsed_s": round(time.time() - t0, 2),
        "raw_tail_lines": raw_lines[-4:],
    }


def main() -> int:
    conv = _load_conv()
    ui = _ui_config_evidence(conv)
    plugin = _plugin_target()

    health_code, health, _ = _get_json(f"{GATEWAY}/health", timeout=5.0)
    gw_body = {
        "model": "demo/aster",
        "messages": [{"role": "user", "content": TEST_PROMPT}],
        "max_tokens": 400,
        "temperature": 0.7,
        "stream": False,
    }
    gw_code, gw_resp, gw_elapsed = _post_json(f"{GATEWAY}/v1/chat/completions", gw_body)
    gw_stream = _stream_capture(
        f"{GATEWAY}/v1/chat/completions",
        {**gw_body, "stream": True},
    )

    lm_body = {
        "model": "qwen/qwen3.5-9b",
        "messages": [{"role": "user", "content": TEST_PROMPT}],
        "max_tokens": 400,
        "temperature": 0.7,
        "stream": False,
    }
    lm_code, lm_resp, lm_elapsed = _post_json(f"{LM}/v1/chat/completions", lm_body)

    gw_json = gw_resp if isinstance(gw_resp, dict) else {}
    lm_json = lm_resp if isinstance(lm_resp, dict) else {}
    gw_choice = (gw_json.get("choices") or [{}])[0]
    gw_usage = gw_json.get("usage") or {}
    gw_det = gw_usage.get("completion_tokens_details") or {}

    active_model = (conv.get("lastUsedModel") or {}).get("identifier")
    token_src = conv.get("tokenSourceIdentifier") or conv.get("lastUsedTokenSource")
    plugins = conv.get("plugins") or []

    if token_src and token_src.get("type") == "generator":
        path_verdict = "gateway_via_generator_plugin"
        request_url = plugin["inferred_post_url"]
    elif active_model == "demo/aster" or "demo/aster" in plugins:
        path_verdict = "gateway_via_generator_plugin"
        request_url = plugin["inferred_post_url"]
    elif active_model and "qwen" in str(active_model):
        path_verdict = "lm_studio_direct_1234"
        request_url = f"{LM}/v1/chat/completions"
    else:
        path_verdict = "unknown"
        request_url = None

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "test_prompt": TEST_PROMPT,
        "2a_request_attribution": {
            "verdict": path_verdict,
            "request_url": request_url,
            "ui_config_evidence": ui,
            "plugin_config_evidence": plugin,
            "interpretation": (
                "Aster tab configured with generator demo/aster → plugin POSTs :8501; "
                "LM Studio :1234 is substrate only unless user picks qwen/qwen3.5-9b."
                if path_verdict == "gateway_via_generator_plugin"
                else "Aster tab lastUsedModel points at local qwen — traffic is :1234 direct; "
                "sanitizer/quarantine/budget on :8501 do not apply."
            ),
            "switch_to_8501_effort_if_direct": (
                "Already on generator path — keep lms dev running, select demo/aster."
                if path_verdict == "gateway_via_generator_plugin"
                else "~0 code (deploy + lms dev + select demo/aster); conversation JSON patch only."
            ),
        },
        "2b_gateway_non_stream_probe": {
            "http_status": gw_code,
            "elapsed_s": round(gw_elapsed, 2),
            "served_by": gw_json.get("served_by"),
            "route_id": gw_json.get("route_id"),
            "ts": gw_json.get("ts"),
            "finish_reason": gw_choice.get("finish_reason"),
            "usage": gw_usage,
            "reasoning_tokens": gw_det.get("reasoning_tokens"),
            "content_preview": (gw_choice.get("message") or {}).get("content", "")[:240],
            "raw_response": gw_json,
        },
        "2b_gateway_stream_probe": gw_stream,
        "2b_lm_direct_control": {
            "http_status": lm_code,
            "elapsed_s": round(lm_elapsed, 2),
            "served_by": lm_json.get("served_by") if isinstance(lm_json, dict) else None,
            "has_served_by": bool(isinstance(lm_json, dict) and lm_json.get("served_by")),
            "finish_reason": (lm_json.get("choices") or [{}])[0].get("finish_reason")
            if isinstance(lm_json, dict)
            else None,
            "usage": lm_json.get("usage") if isinstance(lm_json, dict) else None,
        },
        "2c_streaming_implementation": {
            "gateway_to_substrate": "真流式：gateway async stream POST → LM Studio :1234，逐 chunk 转发给客户端",
            "sanitizer_on_stream": "部分：cleanroom/contract 对累计文本逐 chunk 增量检（stream_incremental_gate）；substrate airlock sanitizer 在流结束后 _record_substrate 才跑",
            "plugin_aster_tab": "非流式：demo/aster generator fetch :8501 stream:false，一次 fragmentGenerated",
        },
        "gateway_health": health if isinstance(health, dict) else {"error": health, "code": health_code},
        "reproduction_matrix_path": str(MATRIX),
        "reproduction_matrix_present": MATRIX.is_file(),
        "empty_after_sanitize_552_autopsy": (
            "reasoning 通道误路由：552 tokens 成品落在 reasoning_content、content 为空；"
            "sanitizer 按设计隔离后 quarantine boundary 清零 → empty_after_sanitize（非 tag 误杀、非 thinking 独白）"
        ),
        "empty_after_sanitize_doc": str(ROOT / "grid-sovereign-runtime/traces/proof/RUN1_QUARANTINE_ANALYSIS.md"),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"wrote": str(OUT), "verdict": path_verdict, "served_by": gw_json.get("served_by")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
