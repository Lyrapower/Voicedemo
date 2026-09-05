"""Shared Grid task-route client for Aether compile nodes (report-only)."""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from grid_compile_hygiene import detect_field_drift, parse_premarket_items, quarantine_drift
from aether_grid_verify import attach_aster_chat_verification

logger = logging.getLogger(__name__)

GATEWAY_URL = os.getenv("GARDEN_GATEWAY_URL", "http://127.0.0.1:8501").rstrip("/")
GATEWAY_MODEL = os.getenv("ASTER_GATEWAY_MODEL", "demo/aster")
GATEWAY_TIMEOUT = float(os.getenv("GRID_COMPILE_TIMEOUT", "180"))
DRIFT_TRACE_DIR = os.getenv(
    "GRID_DRIFT_TRACE_DIR",
    str(__import__("pathlib").Path(__file__).resolve().parent.parent / "grid-sovereign-runtime" / "traces" / "drift"),
)

PREMARKET_SYSTEM = """你是 Aether Nexus 盘前编译节点。只输出候选列表，不输出交易指令。
必须严格使用以下五字段格式，每条一行块，输出 3-5 个候选：

标的：SYMBOL|方向：多/空/观察|为什么今天：（一句）|风险：（一句）|置信：[高置信/试探性/观察]

规则：数据不全时宁可少给不可错给；缺核心因子的标的只给[观察]不给方向。"""

POSTMARKET_COMPILE_SYSTEM = """你是 Aether Nexus 盘后复盘编译节点。只输出观点摘要，不输出交易指令。
格式：
今日做对：（一条，一句）
今日做错：（一条，一句）
次日关注：
- 标的：SYMBOL|方向：多/空/观察|为什么明天：（一句）|风险：（一句）|置信：[高置信/试探性/观察]
（1-3条）

禁止复述原始日志数字；给出判断与关注理由。
禁止输出 JSON；禁止 candidate_count / top_symbol 等 schema 字段。"""


def _valid_postmarket_compile(text: str, meta: dict[str, Any]) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if (meta.get("grid_meta") or {}).get("blocked"):
        return False
    if t.startswith("{") and ("candidate_count" in t or "top_symbol" in t):
        return False
    return "今日做对" in t or "次日关注" in t


def _task_tools(name: str, description: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


def gateway_task_chat(
    *,
    system_prompt: str,
    user_prompt: str,
    tool_name: str,
    tool_description: str,
) -> tuple[str, dict[str, Any]]:
    body = {
        "model": GATEWAY_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "stream": False,
        "_grid_unsafe_debug": False,
        "tools": _task_tools(tool_name, tool_description),
    }
    try:
        body = attach_aster_chat_verification(body, gateway_url=f"{GATEWAY_URL}/v1/chat/completions")
    except Exception as exc:
        meta: dict[str, Any] = {"gateway_url": GATEWAY_URL, "model": GATEWAY_MODEL, "error": str(exc)}
        return "", meta
    req = urllib.request.Request(
        f"{GATEWAY_URL}/v1/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    meta = {"gateway_url": GATEWAY_URL, "model": GATEWAY_MODEL}
    try:
        with urllib.request.urlopen(req, timeout=GATEWAY_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        meta["error"] = str(exc)
        return "", meta
    meta["grid_meta"] = payload.get("grid_meta") or {}
    choices = payload.get("choices") or []
    text = ""
    if choices:
        text = (choices[0].get("message") or {}).get("content") or ""
    return text.strip(), meta


def compile_premarket(user_prompt: str) -> tuple[list[dict[str, Any]] | None, str, dict[str, Any]]:
    text, meta = gateway_task_chat(
        system_prompt=PREMARKET_SYSTEM,
        user_prompt=user_prompt,
        tool_name="aether_premarket_compile",
        tool_description="Premarket candidate compile (task budget).",
    )
    if detect_field_drift(text):
        quarantine_drift(text, context="premarket", trace_dir=__import__("pathlib").Path(DRIFT_TRACE_DIR), raw_prompt=user_prompt)
        return None, text, meta
    items = parse_premarket_items(text)
    return items, text, meta


def compile_postmarket_review(user_prompt: str) -> tuple[str | None, str, dict[str, Any]]:
    text, meta = gateway_task_chat(
        system_prompt=POSTMARKET_COMPILE_SYSTEM,
        user_prompt=user_prompt,
        tool_name="aether_postmarket_compile",
        tool_description="Post-market review compile (task budget).",
    )
    if detect_field_drift(text):
        quarantine_drift(text, context="postmarket", trace_dir=__import__("pathlib").Path(DRIFT_TRACE_DIR), raw_prompt=user_prompt)
        return None, text, meta
    if not _valid_postmarket_compile(text, meta):
        return None, text, meta
    return text, text, meta
