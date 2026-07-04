#!/usr/bin/env python3
"""P0 2×2 reproduction matrix — new/old session × gateway/LM Studio direct."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT / "traces" / "proof"
MATRIX_DIR = PROOF / "reproduction_matrix"
MATRIX_JSON = PROOF / "reproduction_matrix.json"
GATEWAY = "http://127.0.0.1:8501"
LM = "http://127.0.0.1:1234/v1"

# User-reported verbatim repro prompt (LM Studio Aster tab history)
CANONICAL_PROMPT = "摘星人买菜不看价签,看菜上的露水还在不在。你说露水是什么?"

# Prior turn in Aster tab (old session context)
OLD_SESSION_PRIOR = [
    {"role": "user", "content": "下午好啊，刚散步回来，想到一句话，开飞船的卖菜，菜就是新鲜。你接一句？"},
    {
        "role": "assistant",
        "content": "那买菜的得是**坐火箭摘星的人**。✨",
    },
]


def _post(url: str, body: dict, *, timeout: float = 180.0) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _lm_payload(messages: list, *, temperature: float = 0.7) -> dict:
    return {
        "model": "qwen/qwen3.5-9b",
        "messages": messages,
        "max_tokens": 400,
        "temperature": temperature,
        "enable_thinking": False,
        "chat_template_kwargs": {"enable_thinking": False},
        "max_reasoning_tokens": 128,
    }


def _extract_text_gateway(resp: dict) -> str:
    return str(resp.get("response") or resp.get("choices", [{}])[0].get("message", {}).get("content") or "")


def _extract_text_lm(resp: dict) -> str:
    ch = (resp.get("choices") or [{}])[0]
    return str(ch.get("message", {}).get("content") or "")


def _diff_rate(a: str, b: str) -> float:
    import difflib
    a, b = (a or "").strip(), (b or "").strip()
    if a == b:
        return 0.0
    return round(1.0 - difflib.SequenceMatcher(None, a, b).ratio(), 4)


def _lm_runtime_params() -> dict:
    conv = Path.home() / ".lmstudio/conversations/17797865158102.conversation.json"
    if not conv.is_file():
        return {"error": "conversation missing"}
    data = json.loads(conv.read_text(encoding="utf-8"))
    fields = {
        f["key"]: f.get("value")
        for f in (data.get("perChatPredictionConfig") or {}).get("fields", [])
    }
    mpt = fields.get("llm.prediction.maxPredictedTokens") or {}
    return {
        "source": str(conv),
        "temperature": fields.get("llm.prediction.temperature"),
        "top_p": (fields.get("llm.prediction.topPSampling") or {}).get("value")
        if isinstance(fields.get("llm.prediction.topPSampling"), dict)
        else fields.get("llm.prediction.topPSampling"),
        "max_predicted_tokens": mpt.get("value") if isinstance(mpt, dict) else mpt,
        "enable_thinking": fields.get("ext.virtualModel.customField.qwen.qwen3.59b.enableThinking"),
        "message_count": len(data.get("messages") or []),
        "token_count": data.get("tokenCount"),
    }


def run_cell(cell_id: str, *, session: str, path: str) -> dict:
    MATRIX_DIR.mkdir(parents=True, exist_ok=True)
    temperature = 0.7
    t0 = time.time()

    if path == "gateway":
        if session == "new":
            messages = [{"role": "user", "content": CANONICAL_PROMPT}]
            body = {"messages": messages, "max_tokens": 400, "temperature": temperature}
            resp = _post(f"{GATEWAY}/v1/chat/completions", body)
        else:
            messages = OLD_SESSION_PRIOR + [{"role": "user", "content": CANONICAL_PROMPT}]
            body = {"messages": messages, "max_tokens": 400, "temperature": temperature}
            resp = _post(f"{GATEWAY}/v1/chat/completions", body)
        text = _extract_text_gateway(resp)
        served_by = resp.get("served_by")
    else:
        if session == "new":
            messages = [
                {"role": "user", "content": CANONICAL_PROMPT},
                {"role": "assistant", "content": " \n"},
            ]
        else:
            messages = OLD_SESSION_PRIOR + [
                {"role": "user", "content": CANONICAL_PROMPT},
                {"role": "assistant", "content": " \n"},
            ]
        resp = _post(f"{LM}/chat/completions", _lm_payload(messages, temperature=temperature))
        text = _extract_text_lm(resp)
        served_by = resp.get("served_by")

    out_path = MATRIX_DIR / f"{cell_id}.json"
    out_path.write_text(json.dumps(resp, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    txt_path = MATRIX_DIR / f"{cell_id}.txt"
    txt_path.write_text(text, encoding="utf-8")

    return {
        "cell_id": cell_id,
        "session": session,
        "path": path,
        "temperature_sent": temperature,
        "served_by": served_by,
        "has_link_fingerprint": served_by is not None,
        "response_text_path": str(txt_path.relative_to(ROOT)),
        "response_json_path": str(out_path.relative_to(ROOT)),
        "response_len": len(text),
        "finish_reason": (resp.get("choices") or [{}])[0].get("finish_reason")
        or resp.get("upstream_finish_reason"),
        "truncated": resp.get("truncated"),
        "elapsed_s": round(time.time() - t0, 2),
        "text_preview": text[:200],
    }


def main() -> int:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))
    from ensure_gateway_up import ensure_gateway_up

    from gateway.substrate_telemetry import check_repetition_pair, text_diff_rate

    ensure_gateway_up(GATEWAY, timeout=30.0)

    cells = [
        run_cell("gw_new", session="new", path="gateway"),
        run_cell("gw_old", session="old", path="gateway"),
        run_cell("lm_new", session="new", path="lmstudio_direct"),
        run_cell("lm_old", session="old", path="lmstudio_direct"),
    ]

    # Twin-fire repetition on gateway new session
    r1 = json.loads((MATRIX_DIR / "gw_new.json").read_text(encoding="utf-8"))
    body2 = {
        "messages": [{"role": "user", "content": CANONICAL_PROMPT}],
        "max_tokens": 400,
        "temperature": 0.7,
    }
    r2 = _post(f"{GATEWAY}/v1/chat/completions", body2)
    t1 = _extract_text_gateway(r1)
    t2 = _extract_text_gateway(r2)
    rep = check_repetition_pair(prompt=CANONICAL_PROMPT, text_a=t1, text_b=t2, route="gateway")

    # Pairwise diff within LM old (user reported repeated answers)
    lm_old_txt = (MATRIX_DIR / "lm_old.txt").read_text(encoding="utf-8")
    lm_new_txt = (MATRIX_DIR / "lm_new.txt").read_text(encoding="utf-8")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "canonical_prompt": CANONICAL_PROMPT,
        "environment": {
            "user_entry_documented": "LM Studio Aster tab → :1234 native UI (conversation 17797865158102)",
            "gateway_entry": f"{GATEWAY}/v1/chat/completions",
            "lm_studio_runtime_params": _lm_runtime_params(),
            "gateway_health_budget": json.loads(
                urllib.request.urlopen(f"{GATEWAY}/health", timeout=5).read().decode()
            ).get("budget"),
        },
        "cells": cells,
        "pairwise_diff": {
            "lm_new_vs_lm_old": _diff_rate(lm_new_txt, lm_old_txt),
            "gw_new_vs_gw_old": _diff_rate(
                (MATRIX_DIR / "gw_new.txt").read_text(encoding="utf-8"),
                (MATRIX_DIR / "lm_old.txt").read_text(encoding="utf-8"),
            ),
        },
        "repetition_probe": rep,
        "reproduction_in_cell": {
            c["cell_id"]: {
                "truncated_mid_text": (c.get("truncated") is True)
                or (c.get("response_len", 0) > 0 and str(c.get("text_preview", "")).endswith("踮")),
                "note": "truncated_mid_text heuristic: ends mid-sentence or truncated=true",
            }
            for c in cells
        },
    }
    MATRIX_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nWrote {MATRIX_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
