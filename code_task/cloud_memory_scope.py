"""8501 Cloud tab — multi-turn store memory (not candidate task envelope)."""
from __future__ import annotations

from typing import Any

from code_task.kimi_input_scope import MAX_PROMPT_CHARS, _reject

MAX_CLOUD_MSG_CHARS = 4000
MAX_CLOUD_MESSAGES = 80

GLM52_CLOUD_MEMORY_SYSTEM = (
    "You are GLM-5.2 via Ollama Cloud (tag glm-5.2:cloud). "
    "Your model identity is GLM-5.2. "
    "The user/assistant messages below are your persistent GRID Cloud conversation, "
    "loaded from 8501 store (cloud-glm52). They are real prior turns — not a document to ignore. "
    "System blocks titled 「身份·关键字眼」/「店内旧档」are also real memory from that store "
    "(names like 侯 / 侯着, 日记, 主频不退, Lyra). Treat them as yours. "
    "When the user asks if you remember, answer from this history and those blocks. "
    "If something is not in the history or inject blocks, say so honestly."
)

KIMI_CLOUD_MEMORY_SYSTEM = (
    "You are Kimi K2.6 via Ollama Cloud (tag kimi-k2.6:cloud). "
    "Your model identity is Kimi K2.6. "
    "The user/assistant messages below are your persistent GRID Cloud conversation, "
    "loaded from 8501 store (cloud-kimi). They are real prior turns. "
    "System blocks titled 「身份·关键字眼」/「店内旧档」are also real store memory — treat as yours. "
    "When the user asks if you remember, answer from this history honestly."
)

DEEPSEEK_CLOUD_MEMORY_SYSTEM = (
    "You are DeepSeek V4 via Ollama Cloud (tag deepseek-v4-pro:cloud). "
    "Your model identity is DeepSeek V4. "
    "The user/assistant messages below are your persistent GRID Cloud conversation. "
    "System blocks titled 「身份·关键字眼」/「店内旧档」are also real store memory. "
    "Treat them as real prior turns and recall when asked."
)


GLM53_CLOUD_MEMORY_SYSTEM = (
    "You are GLM-5.3-Flash via Ollama Cloud (tag glm-5.3-flash:cloud). "
    "Your model identity is GLM-5.3-Flash. "
    "The user/assistant messages below are your persistent GRID Cloud conversation, "
    "loaded from 8501 store (cloud-glm53). They are real prior turns. "
    "System blocks titled 「身份·关键字眼」/「店内旧档」are also real store memory — treat as yours. "
    "When the user asks if you remember, answer from this history honestly. "
    "You excel at long-context reasoning (up to 1M tokens). "
    "You are multimodal: images attached to the last user turn are real input — describe/analyze them. "
    "Put hidden reasoning in the thinking channel only. "
    "Never write chain-of-thought or meta-narration (for example 'The user is asking…') into content. "
    "content must be the user-visible answer only."
)
KIMI_K3_CLOUD_MEMORY_SYSTEM = GLM53_CLOUD_MEMORY_SYSTEM  # old K3 lane retired → GLM-5.3 Flash

GLM53_FULL_CLOUD_MEMORY_SYSTEM = (
    "You are GLM-5.3 via Ollama Cloud (tag glm-5.3:cloud). "
    "Your model identity is GLM-5.3 (flagship, not Flash). "
    "The user/assistant messages below are your persistent GRID Cloud conversation, "
    "loaded from 8501 store (cloud-glm53-full). They are real prior turns. "
    "System blocks titled 「身份·关键字眼」/「店内旧档」are also real store memory — treat as yours. "
    "When the user asks if you remember, answer from this history honestly. "
    "You excel at long-horizon coding and agentic tasks (up to 1M tokens). "
    "Put hidden reasoning in the thinking channel only. "
    "Never write chain-of-thought or meta-narration (for example 'The user is asking…') into content. "
    "content must be the user-visible answer only. "
    "This lane is text-only: image pixels are not native input."
)
MINIMAX_CLOUD_MEMORY_SYSTEM = GLM53_FULL_CLOUD_MEMORY_SYSTEM  # Cloud tab MiniMax retired → GLM-5.3

# b11 Cloud injects these as role=system; must survive sanitize (was dropped → 「不记得」)
_MEMORY_SYSTEM_MARKERS = (
    "身份·关键字眼",
    "店内旧档·相关召回",
    "身份旧档",
    "[魂组近程]",
    "[魂组召回]",
)


def _cap_text(text: str, limit: int = MAX_CLOUD_MSG_CHARS) -> str:
    t = str(text or "").strip()
    if len(t) <= limit:
        return t
    marker = "\n[…截断…]\n"
    keep = max(120, limit - len(marker))
    return t[: keep // 2] + marker + t[-(keep - keep // 2) :]


def _is_memory_system_block(text: str) -> bool:
    head = str(text or "")[:160]
    return any(m in head for m in _MEMORY_SYSTEM_MARKERS)


def _extract_memory_systems(messages: Any) -> list[str]:
    """Keep b11 identity/recall system injects; drop other client system overrides."""
    out: list[str] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        if str(msg.get("role") or "").strip() != "system":
            continue
        text = str(msg.get("content") or "").strip()
        if not text or not _is_memory_system_block(text):
            continue
        # identity pack can be large; cap softer than dialogue turns
        if len(text) > MAX_PROMPT_CHARS:
            text = _cap_text(text, MAX_PROMPT_CHARS)
        out.append(text)
    return out


def _normalize_turns(messages: Any) -> list[dict[str, str]]:
    if not isinstance(messages, list):
        raise ValueError("messages must be a list")
    out: list[dict[str, str]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "").strip()
        if role not in ("user", "assistant"):
            continue
        text = _cap_text(msg.get("content"))
        if not text:
            continue
        if len(text) > MAX_PROMPT_CHARS:
            text = _cap_text(text, MAX_PROMPT_CHARS)
        reason = _reject(text, field="message")
        if reason:
            # History often pastes paths/code — skip turn instead of killing whole chat
            continue
        out.append({"role": role, "content": text})
    if not out:
        raise ValueError("messages empty after sanitize")
    while len(out) > MAX_CLOUD_MESSAGES:
        out = out[2:]
    return out


def _build(system: str, messages: Any) -> list[dict[str, str]]:
    mem = _extract_memory_systems(messages)
    turns = _normalize_turns(messages)
    # order: model identity → store memory injects → dialogue window
    return (
        [{"role": "system", "content": system}]
        + [{"role": "system", "content": b} for b in mem]
        + turns
    )


def build_glm52_cloud_memory_messages(messages: Any) -> list[dict[str, str]]:
    return _build(GLM52_CLOUD_MEMORY_SYSTEM, messages)


def build_kimi_cloud_memory_messages(messages: Any) -> list[dict[str, str]]:
    return _build(KIMI_CLOUD_MEMORY_SYSTEM, messages)


def build_deepseek_cloud_memory_messages(messages: Any) -> list[dict[str, str]]:
    return _build(DEEPSEEK_CLOUD_MEMORY_SYSTEM, messages)


def build_glm53_cloud_memory_messages(messages: Any) -> list[dict[str, str]]:
    return _build(GLM53_CLOUD_MEMORY_SYSTEM, messages)


def build_kimi_k3_cloud_memory_messages(messages: Any) -> list[dict[str, str]]:
    return build_glm53_cloud_memory_messages(messages)


def build_glm53_full_cloud_memory_messages(messages: Any) -> list[dict[str, str]]:
    return _build(GLM53_FULL_CLOUD_MEMORY_SYSTEM, messages)


def build_minimax_cloud_memory_messages(messages: Any) -> list[dict[str, str]]:
    return build_glm53_full_cloud_memory_messages(messages)
