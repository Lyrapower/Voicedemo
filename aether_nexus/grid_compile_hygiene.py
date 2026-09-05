"""Output hygiene for Grid compile pipeline (report-only, store delivery)."""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from aether_grid_emit import emit_deny

CONFIDENCE_LEVELS = frozenset({"高置信", "试探性", "观察"})
DRIFT_PATTERN = re.compile(
    r"intent_vector|\bHz\b|lattice|coherence|场域|substrate_verdict",
    re.I,
)

PREMARKET_BLOCK = re.compile(
    r"标的[：:]\s*(?P<sym>[A-Z0-9.\-]+)\s*"
    r"(?:\||\n|\r\n)?方向[：:]\s*(?P<direction>[^\n|]+?)\s*"
    r"(?:\||\n|\r\n)?为什么今天[：:]\s*(?P<why>[^\n|]+)\s*"
    r"(?:\||\n|\r\n)风险[：:]\s*(?P<risk>[^\n|]+?)\s*"
    r"(?:\||\n|\r\n)?置信[：:]\s*[\[【]?(?P<conf>高置信|试探性|观察)[\]】]?",
    re.I,
)


def detect_field_drift(text: str) -> bool:
    return bool(DRIFT_PATTERN.search(text or ""))


def direction_to_dir(direction: str) -> int:
    d = (direction or "").strip().lower()
    if any(x in d for x in ("多", "long", "涨", "bull")):
        return 1
    if any(x in d for x in ("空", "short", "跌", "bear")):
        return -1
    return 0


def parse_premarket_items(text: str) -> list[dict[str, Any]] | None:
    """Parse Grid premarket compile. Returns None if whole response drifts."""
    if detect_field_drift(text):
        return None
    items: list[dict[str, Any]] = []
    for m in PREMARKET_BLOCK.finditer(text or ""):
        conf = m.group("conf")
        if conf not in CONFIDENCE_LEVELS:
            continue
        sym = m.group("sym").strip().upper()
        direction = m.group("direction").strip()
        why = m.group("why").strip()
        risk = m.group("risk").strip()
        if not sym:
            continue
        items.append(
            {
                "sym": sym,
                "label": "盘前",
                "value": f"{direction} · [{conf}]",
                "note": f"{why} | 风险：{risk}",
                "dir": direction_to_dir(direction),
                "confidence": conf,
            }
        )
    return items


def quarantine_drift(
    text: str,
    *,
    context: str,
    trace_dir: Path,
    raw_prompt: str = "",
) -> None:
    trace_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = trace_dir / f"drift_{context}_{stamp}.json"
    payload = {
        "context": context,
        "generated_at": dt.datetime.now().isoformat(),
        "drift_detected": True,
        "text_excerpt": (text or "")[:4000],
        "prompt_excerpt": (raw_prompt or "")[:2000],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    emit_deny(
        reason="field_drift",
        detail=f"{context} compile blocked (field vocabulary drift)",
        trace_file=f"traces/drift/{path.name}",
    )
