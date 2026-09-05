"""Sentinel attention budget — report-only signals for Lyra review.

Momentum sticker and other sidecars append here; never feeds pool scan signals.
"""

from __future__ import annotations

import datetime
import json
import os
import tempfile
from typing import Any, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(BASE_DIR, "state")
ATTENTION_PATH = os.path.join(STATE_DIR, "sentinel_attention_budget.json")
MAX_ITEMS = int(os.getenv("SENTINEL_ATTENTION_MAX", "40"))
TTL_HOURS = int(os.getenv("SENTINEL_ATTENTION_TTL_H", "48"))


def _atomic_write(filepath: str, data: Any) -> None:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=os.path.dirname(filepath), delete=False, suffix=".tmp") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            tmp = f.name
        os.replace(tmp, filepath)
    except OSError:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


def _load() -> list[dict]:
    try:
        with open(ATTENTION_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _prune(items: list[dict]) -> list[dict]:
    cutoff = datetime.datetime.now(datetime.timezone.utc).timestamp() - TTL_HOURS * 3600
    out = [i for i in items if i.get("ts", 0) >= cutoff]
    return out[-MAX_ITEMS:]


def add_attention(
    source: str,
    symbol: str,
    signal: str,
    detail: str,
    *,
    priority: str = "normal",
    tags: Optional[list[str]] = None,
) -> dict:
    """Append one attention item; returns the row written."""
    row = {
        "ts": datetime.datetime.now(datetime.timezone.utc).timestamp(),
        "time": datetime.datetime.now().astimezone().isoformat(),
        "source": source,
        "symbol": symbol.upper(),
        "signal": signal,
        "detail": detail[:800],
        "priority": priority,
        "tags": tags or [],
        "report_only": True,
    }
    items = _prune(_load())
    items.append(row)
    _atomic_write(ATTENTION_PATH, items)
    return row


def recent(limit: int = 20) -> list[dict]:
    return _prune(_load())[-limit:]
