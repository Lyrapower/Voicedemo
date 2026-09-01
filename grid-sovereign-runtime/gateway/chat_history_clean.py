"""Strip machine envelopes and UI telemetry before chat inference."""
from __future__ import annotations

import json
import re
from typing import Any

_INJECTED_BLOCK = re.compile(
    r"\n?\[(?:GRID_ABSENT:[^\]]*|Boundary:[^\]]*)\]",
    re.IGNORECASE,
)


def is_trade_action_envelope(text: str) -> bool:
    t = (text or "").strip()
    if not t.startswith("{"):
        return False
    if "CONTRACT:TRADE_ACTION" in t and "candidate_count" in t:
        return True
    try:
        obj = json.loads(t)
    except json.JSONDecodeError:
        return False
    flags = obj.get("anomaly_flags") or []
    return isinstance(flags, list) and "CONTRACT:TRADE_ACTION" in flags


def is_stale_machine_envelope(text: str) -> bool:
    if is_trade_action_envelope(text):
        return True
    t = (text or "").strip()
    if t.startswith("{") and "anomaly_flags" in t and "data_suspect" in t:
        return True
    if t.startswith("[") and "CONTRACT:" in t and len(t) < 8000:
        inner = t.strip("[]")
        if inner.startswith("{") and is_trade_action_envelope(inner):
            return True
    return False


def clean_message_for_inference(content: str) -> str:
    t = str(content or "")
    if is_stale_machine_envelope(t):
        return ""
    t = _INJECTED_BLOCK.sub("", t)
    if is_trade_action_envelope(t.strip()):
        return ""
    return t.strip()


def clean_chat_messages(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    """Return inference-safe messages and whether stale envelopes were dropped."""
    stale = False
    out: list[dict[str, Any]] = []
    for msg in messages or []:
        role = msg.get("role")
        if role not in ("user", "assistant", "system"):
            continue
        content = msg.get("content")
        if not isinstance(content, str):
            out.append(dict(msg))
            continue
        if role == "assistant" and is_stale_machine_envelope(content):
            stale = True
            continue
        cleaned = clean_message_for_inference(content)
        if role == "assistant" and content.strip() and not cleaned:
            stale = True
            continue
        nm = dict(msg)
        nm["content"] = cleaned if cleaned else content
        out.append(nm)
    return out, stale


def normalize_substrate_dialog(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    """Qwen/LM Studio jinja requires non-empty user turns; dialog must not lead with assistant."""
    cleaned, stale = clean_chat_messages(messages)
    systems: list[dict[str, Any]] = []
    dialog: list[dict[str, Any]] = []
    for msg in cleaned:
        role = msg.get("role")
        if role == "system":
            systems.append(dict(msg))
            continue
        if role not in ("user", "assistant"):
            continue
        content = str(msg.get("content") or "").strip()
        if not content:
            stale = True
            continue
        dialog.append({"role": role, "content": content})
    while dialog and dialog[0]["role"] == "assistant":
        dialog.pop(0)
        stale = True
    return systems + dialog, stale


def had_stale_envelopes(messages: list[dict[str, Any]]) -> bool:
    for msg in messages or []:
        if msg.get("role") != "assistant":
            continue
        if is_stale_machine_envelope(str(msg.get("content") or "")):
            return True
    return False
