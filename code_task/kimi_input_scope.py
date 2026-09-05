"""Task-scoped input builder for Kimi K2.6 Cloud candidate lane."""
from __future__ import annotations

import re
from typing import Any

MAX_PROMPT_CHARS = 8000
MAX_IMAGES = 2
MAX_IMAGES_EXPANDED = 6
MAX_IMAGE_B64_CHARS = 1_500_000

_FORBIDDEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)field_now"),
    re.compile(r"(?i)\bdiary\.db\b"),
    re.compile(r"(?i)memory\s*palace"),
    re.compile(r"(?i)seven[- ]day\s+history"),
    re.compile(r"(?i)grid\s+system\s+prompt"),
    re.compile(r"(?i)\b(?:sk|api)[_-]?key\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\b(?:wallet|mnemonic|seed\s+phrase)\b"),
    re.compile(r"(?i)\b(?:/Users/|/home/|C:\\\\|~/Projects/)"),
    re.compile(r"(?i)\bdemo/aster\b.*\bsystem\b"),
    re.compile(r"(?i)<think>"),
)

_GRID_ANCHOR_MARKERS = (
    "你是 Aster",
    "You are Aster",
    "PACK 1",
    "NULL contract",
    "Chenxi anchor",
)


def _reject(text: str, *, field: str) -> str | None:
    for pat in _FORBIDDEN_PATTERNS:
        if pat.search(text):
            return f"{field} matches forbidden pattern: {pat.pattern[:48]}"
    for marker in _GRID_ANCHOR_MARKERS:
        if marker in text:
            return f"{field} contains Grid anchor marker"
    return None


def _normalize_images(raw: Any, *, max_images: int | None = None) -> list[dict[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("images must be a list")
    limit = MAX_IMAGES if max_images is None else int(max_images)
    if len(raw) > limit:
        raise ValueError(f"at most {limit} images allowed")
    out: list[dict[str, str]] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"images[{idx}] must be an object")
        b64 = str(item.get("base64") or item.get("data") or "").strip()
        if not b64:
            raise ValueError(f"images[{idx}] missing base64/data")
        if len(b64) > MAX_IMAGE_B64_CHARS:
            raise ValueError(f"images[{idx}] too large")
        mime = str(item.get("mime") or item.get("media_type") or "image/png").strip()
        if not mime.startswith("image/"):
            raise ValueError(f"images[{idx}] mime must be image/*")
        out.append({"base64": b64, "mime": mime})
    return out


def build_task_scoped_messages(
    *,
    prompt: str,
    task_label: str | None = None,
    images: Any = None,
    max_images: int | None = None,
) -> list[dict[str, Any]]:
    """Return minimal Ollama messages for a single scoped task."""
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
    system = (
        "You are a remote candidate model (Ollama Cloud Kimi K2.6). "
        "Answer only the scoped task below. Do not claim Grid authority, "
        "do not invoke tools, and do not reference private memory."
    )
    user_msg: dict[str, Any] = {
        "role": "user",
        "content": f"[{label}]\n{text}",
    }
    if imgs:
        user_msg["images"] = [img["base64"] for img in imgs]

    return [
        {"role": "system", "content": system},
        user_msg,
    ]


KIMI26_IDENTITY_SYSTEM = (
    "You are Kimi K2.6 served via Ollama Cloud (tag kimi-k2.6:cloud). "
    "Your only correct model identity is Kimi K2.6. "
    "When asked what model you are, answer Kimi K2.6 — never Kimi K2, Kimi K3, GLM, Grid, or Aster. "
    "Do not claim Grid authority, tools, or private memory. "
    "Answer only the scoped conversation below."
)


def build_chat_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Multi-turn Kimi tab — inject identity system; drop client system overrides."""
    out: list[dict[str, str]] = [{"role": "system", "content": KIMI26_IDENTITY_SYSTEM}]
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
