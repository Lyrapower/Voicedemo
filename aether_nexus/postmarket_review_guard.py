"""R1 guard — drop unsourced win-rate / close stats; tag fact_gap not confabulation."""
from __future__ import annotations

import re
from typing import Any

_WIN_RATE = re.compile(r"\d+\s*%\s*胜率|win[_\s-]?rate\s*[:=]?\s*\d+|维持\s*\d+\s*%\s*胜率", re.I)
_CLOSE_STAT = re.compile(r"平仓\s*\d+|closed\s+\d+\s+trades|realized\s+p&l", re.I)


def audit_review_text(text: str, *, fact_pack: dict[str, Any] | None = None) -> tuple[str, list[dict[str, Any]]]:
    """Return (cleaned_text, audit_events)."""
    pack = fact_pack or {}
    events: list[dict[str, Any]] = []
    out = text or ""
    if pack.get("zero_realized_close") and _CLOSE_STAT.search(out):
        events.append({"tag": "fact_gap", "reason": "unsourced_close_count"})
        out = _CLOSE_STAT.sub("[fact_gap: 无平仓数据]", out)
    if not pack.get("win_rate_available") and _WIN_RATE.search(out):
        events.append({"tag": "fact_gap", "reason": "unsourced_win_rate"})
        out = _WIN_RATE.sub("[fact_gap: 无胜率可谈·今日零平仓]", out)
    return out, events
