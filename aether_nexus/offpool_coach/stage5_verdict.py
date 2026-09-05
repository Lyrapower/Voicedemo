"""Stage 5 — T+0 verdict vs falsifier (trial rollup)."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

logger = logging.getLogger(__name__)


def evaluate_falsifier(
    *,
    symbol: str,
    falsifier: str,
    trade_date: str,
    direction: int | None = None,
) -> dict[str, Any]:
    """Mechanical T+0 verdict: compare the pick's directional thesis against the
    actual close-to-close return on trade_date.

    M13: previously a hard-coded `PENDING` placeholder ("stage5 not wired"). Now
    fetches the trade-date return and produces a real FALSIFIED / CONFIRMED /
    PENDING verdict. The qualitative `falsifier` text is preserved for audit.

    `direction` is the pick's thesis sign (+1 long / -1 short / 0 observe). When
    absent or 0 the verdict stays PENDING (no directional claim to falsify).
    """
    base = {
        "symbol": symbol,
        "trade_date": trade_date,
        "falsifier": falsifier,
        "direction": direction,
    }
    if direction is None or direction == 0:
        return {**base, "status": "PENDING", "note": "non-directional pick — no thesis to falsify"}

    try:
        from aether_dryrun import get_stock_history  # local import (heavy module)
        from premarket_ab_returns import _day_return_from_hist

        d = dt.date.fromisoformat(trade_date)
        hist, _prov = get_stock_history(symbol)
        ret = _day_return_from_hist(hist, d)
    except Exception as exc:  # data unavailable — surface, don't crash
        logger.warning("stage5 evaluate_falsifier data fetch failed %s: %s", symbol, exc)
        return {**base, "status": "PENDING", "note": f"data_unavailable: {exc.__class__.__name__}"}

    if ret is None:
        return {**base, "status": "PENDING", "note": "no trade-date return (data missing)"}

    base["return_pct"] = round(ret, 6)
    # thesis confirmed when return sign matches direction; falsified when opposed.
    if (direction > 0 and ret > 0) or (direction < 0 and ret < 0):
        return {**base, "status": "CONFIRMED", "note": f"thesis held: ret={ret:+.2%}"}
    if ret == 0:
        return {**base, "status": "PENDING", "note": "flat close — inconclusive"}
    return {**base, "status": "FALSIFIED", "note": f"thesis broken: ret={ret:+.2%} vs dir={direction}"}


def weekly_rollup(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll up per-pick verdicts over a trial window."""
    verdicts = [r for r in rows if isinstance(r, dict)]
    confirmed = sum(1 for r in verdicts if r.get("status") == "CONFIRMED")
    falsified = sum(1 for r in verdicts if r.get("status") == "FALSIFIED")
    pending = sum(1 for r in verdicts if r.get("status") == "PENDING")
    directional = confirmed + falsified
    return {
        "n_days": len({r.get("trade_date") for r in verdicts if r.get("trade_date")}),
        "n_picks": len(verdicts),
        "confirmed": confirmed,
        "falsified": falsified,
        "pending": pending,
        "confirm_rate": round(confirmed / directional, 4) if directional else None,
        "fabrication_violations": sum(1 for r in verdicts if r.get("gated_reason") == "violation:fabricated_number"),
        "note": "T+0 mechanical verdict rollup (close-vs-thesis)",
    }
