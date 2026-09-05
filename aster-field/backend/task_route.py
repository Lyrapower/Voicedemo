"""Task-type token routing for FIELD /chat → gateway."""
from __future__ import annotations

import os
import re


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


TASK_BUDGETS: dict[str, int] = {
    "chat": _int_env("FIELD_CHAT_MAX_TOKENS", 1600),
    "diary": _int_env("FIELD_DIARY_MAX_TOKENS", 1600),
    "compile_json": _int_env("FIELD_COMPILE_MAX_TOKENS", 4096),
    "handoff_protocol": _int_env("FIELD_HANDOFF_MAX_TOKENS", 4096),
}

_JSON_MARKERS = (
    "compile_json", "valid json", "output json", "json only", "仅json", "返回json", "只输出json",
)
_HANDOFF_MARKERS = ("handoff_protocol", "handoff protocol", "交接协议", "handoff pack")
_DIARY_MARKERS = ("这是你的日记本", "日记本。没有任务")


def classify_task(message: str, hint: str | None = None) -> str:
    if hint and hint in TASK_BUDGETS:
        return hint
    low = message.lower()
    if any(m in message for m in _DIARY_MARKERS):
        return "diary"
    if any(m in low for m in _HANDOFF_MARKERS):
        return "handoff_protocol"
    if any(m in low for m in _JSON_MARKERS):
        return "compile_json"
    if "json" in low and re.search(r"\b(compile|schema|artifact|protocol|handoff)\b", low):
        return "compile_json"
    return "chat"


def max_tokens_for(task: str) -> int:
    return TASK_BUDGETS.get(task, TASK_BUDGETS["chat"])


def is_json_task(task: str) -> bool:
    return task in ("compile_json", "handoff_protocol")
