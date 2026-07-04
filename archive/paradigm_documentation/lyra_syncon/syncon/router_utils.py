from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def now_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load_anchor(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def classify_task(messages: list[dict[str, Any]]) -> str:
    text = "\n".join(
        m.get("content", "") for m in messages if isinstance(m, dict)
    ).lower()
    if any(
        k in text
        for k in (
            "def ",
            "class ",
            "import ",
            "traceback",
            "pip install",
            "dockerfile",
            "fastapi",
            "uvicorn",
        )
    ):
        return "coding"
    if any(k in text for k in ("rewrite", "email", "cover letter", "resume", "copy", "tone")):
        return "writing"
    if any(
        k in text
        for k in ("analyze", "tradeoff", "benchmark", "compare", "assumption", "risk")
    ):
        return "analysis"
    return "chat"


def scan_banned_phrases(text: str, banned: list[str]) -> list[str]:
    return [p for p in banned if p and p in text]


def ensure_logs_dir(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)


def append_jsonl(log_path: Path, record: dict[str, Any]) -> None:
    ensure_logs_dir(log_path)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def trim_prompt(text: str, max_chars: int) -> str:
    if max_chars and len(text) > max_chars:
        return text[:max_chars] + "...[TRIM]"
    return text


def build_prompt(messages: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        chunks.append(f"{str(role).upper()}:\n{content}")
    return "\n\n".join(chunks).strip()


def choose_chain(anchor: dict[str, Any], task: str) -> list[str]:
    routing = anchor.get("routing", {})
    tasks = routing.get("tasks", {})
    chain = tasks.get(task) or routing.get("default_chain") or ["local"]
    return list(chain)


class ProviderError(Exception):
    pass
