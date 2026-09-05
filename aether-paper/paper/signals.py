"""Grid/Aster scan 候选 → paper want_pct 信号。"""
from __future__ import annotations

import hashlib
from typing import Any


def score_to_want_pct(score: float) -> float:
    """Scan score → 建议仓位比例(引擎仍过 20% cap)。"""
    if score >= 55:
        return 0.20
    if score >= 50:
        return 0.15
    if score >= 45:
        return 0.12
    if score >= 40:
        return 0.10
    if score >= 35:
        return 0.08
    return 0.0


def signal_key(scan_time: str, symbol: str, scan_mode: str) -> str:
    raw = f"{scan_time}|{symbol.upper()}|{scan_mode}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def candidates_to_signals(
    candidates: list[dict[str, Any]],
    *,
    scan_time: str,
    scan_mode: str,
    label: str = "",
    min_score: float = 35.0,
    max_signals: int = 3,
) -> list[dict[str, Any]]:
    """Top scan hits → paper enter signals (underlying equity, not options)."""
    out: list[dict[str, Any]] = []
    for c in candidates[: max_signals * 2]:
        sym = str(c.get("symbol") or "").upper()
        if not sym:
            continue
        score = float(c.get("score") or 0)
        if score < min_score:
            continue
        want = score_to_want_pct(score)
        if want <= 0:
            continue
        ref = float(c.get("underlying_price") or c.get("last_price") or 0)
        out.append(
            {
                "symbol": sym,
                "want_pct": want,
                "score": score,
                "scan_time": scan_time,
                "scan_mode": scan_mode,
                "label": label or scan_mode,
                "reason": f"grid_scan:{scan_mode}:{label}:score={score:.1f}",
                "ref_price": ref,
                "key": signal_key(scan_time, sym, scan_mode),
            }
        )
        if len(out) >= max_signals:
            break
    return out
