"""Explicit manual backend selection for compile/task lanes on :8501."""
from __future__ import annotations

from typing import Any

MANUAL_BACKEND_IDS = frozenset({"ollama_coder", "cc_cli"})
CANDIDATE_BACKEND_IDS = frozenset({"glm52_cloud", "glm53_flash_cloud", "kimi_k25_cloud", "deepseek_v4_cloud"})
TASK_SCOPED_ROUTES = frozenset({"compile", "task"})
COMPILE_TASK_HINTS = frozenset({"compile_json", "handoff_protocol"})


def substrate_route_class(body: dict[str, Any], chat_route: str) -> str:
    """Map HTTP body to substrate route (compile vs task vs chat)."""
    task = str(body.get("task") or "").strip()
    if task in COMPILE_TASK_HINTS:
        return "compile"
    route = (chat_route or "chat").strip() or "chat"
    return route if route in TASK_SCOPED_ROUTES else route


def parse_candidate_backend_id(body: dict[str, Any]) -> str:
    raw = body.get("backend_id")
    if raw is None or str(raw).strip() == "":
        allowed = ", ".join(sorted(CANDIDATE_BACKEND_IDS))
        raise ValueError(f"backend_id required (allowed: {allowed})")
    bid = str(raw).strip().lower()
    if bid not in CANDIDATE_BACKEND_IDS:
        allowed = ", ".join(sorted(CANDIDATE_BACKEND_IDS))
        raise ValueError(f"invalid backend_id: {raw!r} (allowed: {allowed})")
    return bid


def parse_manual_backend_id(
    body: dict[str, Any],
    *,
    route_class: str,
) -> str | None:
    """Return normalized backend_id when present on a compile/task request."""
    if route_class not in TASK_SCOPED_ROUTES:
        return None
    raw = body.get("backend_id")
    if raw is None or str(raw).strip() == "":
        return None
    bid = str(raw).strip().lower()
    if bid not in MANUAL_BACKEND_IDS:
        raise ValueError(f"invalid backend_id: {raw!r} (allowed: ollama_coder, cc_cli)")
    return bid


def effective_manual_backend_id(
    body: dict[str, Any],
    *,
    route_class: str,
) -> str:
    """Default compile/task backend is ollama_coder; cc_cli only when explicit."""
    if route_class not in TASK_SCOPED_ROUTES:
        return "lm_studio"
    explicit = parse_manual_backend_id(body, route_class=route_class)
    if explicit:
        return explicit
    return "ollama_coder"


def task_scoped_cc_prompt(messages: list[dict[str, Any]], *, route_class: str) -> str:
    """Task-only prompt for CC CLI — no diary, history, or Aster identity anchors."""
    if route_class == "compile":
        parts: list[str] = []
        for msg in messages:
            role = str(msg.get("role") or "")
            content = msg.get("content", "")
            if role not in ("system", "user"):
                continue
            if isinstance(content, str) and content.strip():
                parts.append(content.strip())
        return "\n\n".join(parts).strip()

    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


def cc_cli_allowed(body: dict[str, Any], *, route_class: str) -> bool:
    return effective_manual_backend_id(body, route_class=route_class) == "cc_cli"
