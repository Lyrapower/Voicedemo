"""Per-task substrate temperature for demo/aster — no single global default."""

from __future__ import annotations

CHAT_DIALOGUE_TEMP = 0.8
CANDIDATE_INTEGRATE_TEMP = 0.7
STRUCTURED_TASK_TEMP = 0.3

CANDIDATE_INTEGRATE_LABELS = frozenset({
    "grid_candidate_integrate",
    "candidate_integrate",
    "grid_candidate_integration",
})

CANDIDATE_INTEGRATE_MARKERS = (
    "云端 candidate(仅参考",
    "云端 candidate（仅参考",
)

STRUCTURED_ROUTE_CLASSES = frozenset({"compile", "task", "gateway"})


def is_candidate_integrate_request(
    body: dict | None,
    messages: list | None,
) -> bool:
    body = body or {}
    for key in ("task_label", "task"):
        label = str(body.get(key) or "").strip().lower()
        if label in CANDIDATE_INTEGRATE_LABELS:
            return True
    for msg in reversed(messages or []):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            for marker in CANDIDATE_INTEGRATE_MARKERS:
                if marker in content:
                    return True
        break
    return False


def resolve_substrate_temperature(
    *,
    route_class: str,
    body: dict | None = None,
    messages: list | None = None,
) -> float:
    """Dispatch temperature by route class and task_label / integrate markers."""
    rc = (route_class or "chat").strip().lower()
    if rc in STRUCTURED_ROUTE_CLASSES:
        return STRUCTURED_TASK_TEMP
    if rc == "chat" and is_candidate_integrate_request(body, messages):
        return CANDIDATE_INTEGRATE_TEMP
    if rc == "chat":
        return CHAT_DIALOGUE_TEMP
    return STRUCTURED_TASK_TEMP
