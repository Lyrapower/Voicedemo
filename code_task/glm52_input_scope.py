"""Task-scoped input builder for GLM-5.2 Cloud — identity anchored, not Kimi/Grid."""
from __future__ import annotations

from typing import Any

from code_task.kimi_input_scope import (
    MAX_IMAGES_EXPANDED,
    MAX_PROMPT_CHARS,
    _normalize_images,
    _reject,
)

GLM52_IDENTITY_SYSTEM = (
    "You are GLM-5.2 served via Ollama Cloud (tag glm-5.2:cloud). "
    "Your only correct model identity is GLM-5.2. "
    "When asked what model you are, answer GLM-5.2 — never GLM-4.5, GLM-4, Kimi, Grid, or Aster. "
    "Do not claim Grid authority, tools, or private memory. "
    "Answer only the scoped task below."
)


def build_task_scoped_messages(
    *,
    prompt: str,
    task_label: str | None = None,
    images: Any = None,
    max_images: int | None = None,
) -> list[dict[str, Any]]:
    """Single-turn candidate envelope for EXPANDED / 8501 candidate lane."""
    text = str(prompt or "").strip()
    if not text:
        raise ValueError("prompt required")
    if len(text) > MAX_PROMPT_CHARS:
        raise ValueError(f"prompt exceeds {MAX_PROMPT_CHARS} chars")
    reason = _reject(text, field="prompt")
    if reason:
        raise ValueError(reason)

    imgs = _normalize_images(images, max_images=max_images)
    label = (task_label or "grid_candidate_task").strip()[:80]
    user_msg: dict[str, Any] = {
        "role": "user",
        "content": f"[{label}]\n{text}",
    }
    if imgs:
        user_msg["images"] = [img["base64"] for img in imgs]

    return [
        {"role": "system", "content": GLM52_IDENTITY_SYSTEM},
        user_msg,
    ]


_MEMORY_SYSTEM_MARKERS = (
    "身份·关键字眼",
    "店内旧档·相关召回",
    "身份旧档",
    "[魂组近程]",
    "[魂组召回]",
)


def build_chat_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Multi-turn GLM tab — inject identity system; keep store-memory system; drop other overrides.

    Note: Cloud tab production path uses cloud_memory_scope builders; this stays for parity.
    """
    out: list[dict[str, str]] = [{"role": "system", "content": GLM52_IDENTITY_SYSTEM}]
    mem: list[str] = []
    turns: list[dict[str, str]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "").strip()
        content = msg.get("content")
        if not isinstance(content, str):
            continue
        text = content.strip()
        if not text:
            continue
        if role == "system":
            if any(m in text[:160] for m in _MEMORY_SYSTEM_MARKERS):
                mem.append(text)
            continue
        if role not in ("user", "assistant"):
            continue
        if len(text) > MAX_PROMPT_CHARS:
            raise ValueError(f"message exceeds {MAX_PROMPT_CHARS} chars")
        reason = _reject(text, field="message")
        if reason:
            raise ValueError(reason)
        turns.append({"role": role, "content": text})
    for block in mem:
        out.append({"role": "system", "content": block})
    out.extend(turns)
    if len(out) <= 1:
        raise ValueError("messages empty after sanitize")
    return out
