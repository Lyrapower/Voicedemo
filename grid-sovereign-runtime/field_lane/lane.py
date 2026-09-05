"""Canonical store lanes — grid app and 8790 share the same node_ids."""
from __future__ import annotations

import datetime as dt
import os
import re

NODE_CHAT = os.environ.get("FIELD_CHAT_NODE_ID", "field-particle")
NODE_COMPILE = os.environ.get("FIELD_COMPILE_NODE_ID", "field-compile")
ALL_NODES = (NODE_CHAT, NODE_COMPILE)

ANCHOR_DATE = os.environ.get("FIELD_MEMORY_EPOCH_ANCHOR", "2026-07-16")
EPOCH_DAYS = int(os.environ.get("FIELD_MEMORY_EPOCH_DAYS", os.environ.get("FIELD_MEMORY_DAYS", "7")))

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


def node_for_task(task: str) -> str:
    if task in ("compile_json", "handoff_protocol"):
        return NODE_COMPILE
    return NODE_CHAT


def uses_memory(task: str) -> bool:
    return task in ("chat", "diary", "compile_json", "handoff_protocol")


def _parse_anchor() -> dt.date:
    try:
        return dt.date.fromisoformat(ANCHOR_DATE[:10])
    except ValueError:
        return dt.date(2026, 7, 16)


def current_epoch_start(*, today: dt.date | None = None) -> dt.date:
    today = today or dt.date.today()
    anchor = _parse_anchor()
    if today < anchor:
        return anchor
    idx = (today - anchor).days // max(1, EPOCH_DAYS)
    return anchor + dt.timedelta(days=idx * max(1, EPOCH_DAYS))


def epoch_start_ts(*, today: dt.date | None = None) -> float:
    start = current_epoch_start(today=today)
    return dt.datetime.combine(start, dt.time.min).timestamp()
