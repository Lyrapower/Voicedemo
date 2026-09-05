"""Premarket DeepSeek V4 windows — pipe format: key:HH:MM"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "deepseek-v4-flash:cloud"


@dataclass(frozen=True)
class PremarketDeepseekWindow:
    key: str
    label: str
    hour: int
    minute: int


def _parse_window_chunk(chunk: str) -> PremarketDeepseekWindow | None:
    chunk = chunk.strip()
    if not chunk or ":" not in chunk:
        return None
    key, hm = chunk.split(":", 1)
    key = key.strip()
    hm = hm.strip()
    if not key or ":" not in hm:
        logger.warning("skip bad PREMARKET_DEEPSEEK_WINDOWS entry: %s", chunk)
        return None
    hour_s, minute_s = hm.split(":", 1)
    try:
        hour, minute = int(hour_s), int(minute_s)
    except ValueError:
        logger.warning("skip bad time in PREMARKET_DEEPSEEK_WINDOWS: %s", chunk)
        return None
    label = {"premarket": "PREMARKET", "intraday": "INTRADAY"}.get(key, key.upper())
    return PremarketDeepseekWindow(key=key, label=label, hour=hour, minute=minute)


def default_premarket_deepseek_windows() -> list[PremarketDeepseekWindow]:
    raw = os.getenv("PREMARKET_DEEPSEEK_WINDOWS", "").strip()
    if raw:
        wins = [w for w in (_parse_window_chunk(c) for c in raw.split(",")) if w]
        if wins:
            return wins
    return [
        PremarketDeepseekWindow("premarket", "PREMARKET", 6, 40),
        PremarketDeepseekWindow("intraday", "INTRADAY", 10, 40),
    ]
