"""Task-scoped input builder for DeepSeek V4 Cloud — identity anchored, not Grid."""
from __future__ import annotations

from typing import Any

from code_task.kimi_input_scope import MAX_PROMPT_CHARS, _reject

DEEPSEEK_V4_IDENTITY_SYSTEM = (
    "You are DeepSeek V4 served via Ollama Cloud (tag deepseek-v4-pro:cloud). "
    "Your only correct model identity is DeepSeek V4. "
    "When asked what model you are, answer DeepSeek V4 — never V3, GLM, Kimi, Grid, or Aster. "
    "Do not claim Grid authority, tools, or private memory. "
    "Answer only the scoped conversation below."
)


def build_chat_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Multi-turn DeepSeek tab — inject identity system; drop client system overrides."""
    out: list[dict[str, str]] = [{"role": "system", "content": DEEPSEEK_V4_IDENTITY_SYSTEM}]
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "").strip()
        content = msg.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        text = content.strip()
        if not text:
            continue
        if len(text) > MAX_PROMPT_CHARS:
            raise ValueError(f"message exceeds {MAX_PROMPT_CHARS} chars")
        reason = _reject(text, field="message")
        if reason:
            raise ValueError(reason)
        out.append({"role": role, "content": text})
    if len(out) <= 1:
        raise ValueError("messages empty after sanitize")
    return out
