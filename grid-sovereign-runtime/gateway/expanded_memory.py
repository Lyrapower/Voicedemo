"""Memory snippet selection for expanded orchestration."""
from __future__ import annotations

import re
import time
from typing import Any

from code_task.kimi_input_scope import _reject

_WORD = re.compile(r"[\w\u4e00-\u9fff]{2,}", re.UNICODE)
_OUTBOUND_SAN = re.compile(
    r"/(?:Users|home|var|etc)/[^\s\"'”]+|sk-[A-Za-z0-9]{16,}|"
    r"(?:api[_-]?key|token|secret)\s*[=:]\s*\S+",
    re.I,
)


def _sanitize(text: str) -> tuple[str | None, str | None]:
    reason = _reject(text, field="memory")
    if reason:
        return None, reason
    if _OUTBOUND_SAN.search(text):
        return None, "memory matches local path or secret pattern"
    return text, None


def score_relevance(task: str, snippet: str) -> int:
    task_words = set(_WORD.findall(task.lower()))
    if not task_words:
        return 0
    snippet_words = set(_WORD.findall(snippet.lower()))
    return len(task_words & snippet_words)


def select_store_memory_snippets(
    messages: list[dict[str, Any]],
    *,
    task: str,
    max_snippets: int = 3,
) -> tuple[list[str], list[str]]:
    snippets: list[str] = []
    hits: list[str] = []
    scored: list[tuple[int, str]] = []

    for msg in messages:
        role = str(msg.get("role") or "")
        if role not in ("user", "assistant"):
            continue
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        clean, reason = _sanitize(content)
        if clean:
            scored.append((score_relevance(task, clean), clean[:400]))
        elif reason:
            hits.append(reason)

    scored.sort(key=lambda x: (-x[0], -len(x[1])))
    seen: set[str] = set()
    for score, text in scored:
        if score <= 0 and snippets:
            break
        if text in seen:
            continue
        seen.add(text)
        snippets.append(text)
        if len(snippets) >= max_snippets:
            break
    return snippets, hits


def load_store_messages(
    store: Any | None,
    *,
    node_id: str = "field-particle",
    since_days: int = 7,
) -> list[dict[str, Any]]:
    """优先 grid_mem local 魂组并集;失败再回退单 node。"""
    try:
        import os
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from grid_mem import DEFAULT_STORE_DB, fetch_recall, fetch_turns

        db = os.environ.get("GRID_STORE_DB") or DEFAULT_STORE_DB
        if db and os.path.isfile(db):
            rows = fetch_turns(db, "local", 15)
            return [
                {"role": r["role"], "content": r["content"], "id": r["id"], "ts": r.get("ts")}
                for r in rows
                if r.get("role") in ("user", "assistant")
            ]
    except Exception:
        pass
    if store is None:
        return []
    since_ts = time.time() - since_days * 86400
    try:
        return store.get_messages(node_id, limit=120, since_ts=since_ts)
    except Exception:
        return []


def load_soul_recall(task: str, *, surface: str = "b11-expanded", budget: int = 2000) -> list[str]:
    try:
        import os
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from grid_mem import DEFAULT_STORE_DB, fetch_recall

        db = os.environ.get("GRID_STORE_DB") or DEFAULT_STORE_DB
        if not db or not os.path.isfile(db):
            return []
        return [h["text"] for h in fetch_recall(db, surface, task, budget)]
    except Exception:
        return []
