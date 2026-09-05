"""Fetch intraday/daily returns for premarket A/B scoring — report-only."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _day_return_from_hist(hist: Any, trade_date: dt.date) -> float | None:
    if hist is None or hist.empty:
        return None
    try:
        import pandas as pd

        idx = pd.to_datetime(hist.index).normalize()
        ts = pd.Timestamp(trade_date)
        if ts not in idx:
            # M2: exact trade_date absent from index → treat as data missing.
            # The previous fallback (last two rows ≤ date) returned a return for a
            # *different* calendar day on delayed feeds / timezone-skewed indices.
            return None
        loc = idx.get_loc(ts)
        if isinstance(loc, slice):
            loc = loc.start or 0
        if loc < 1:
            return None
        close_t = float(hist["Close"].iloc[loc])
        close_prev = float(hist["Close"].iloc[loc - 1])
        if close_prev <= 0:
            return None
        return (close_t - close_prev) / close_prev
    except Exception as exc:
        logger.debug("day return parse failed: %s", exc)
        return None


def fetch_day_returns(trade_date: str, symbols: set[str]) -> dict[str, float]:
    """sym -> close-to-close return on trade_date (fraction, e.g. 0.012 = +1.2%)."""
    try:
        from aether_dryrun import get_stock_history
    except ImportError:
        logger.warning("aether_dryrun unavailable for A/B returns")
        return {}
    d = dt.date.fromisoformat(trade_date)
    out: dict[str, float] = {}
    for sym in sorted(s for s in symbols if s and s != "—"):
        hist, _prov = get_stock_history(sym)
        ret = _day_return_from_hist(hist, d)
        if ret is not None:
            out[sym.upper()] = round(ret, 6)
    return out


def chain_signed_return_pct(items: list[dict[str, Any]], outcomes: dict[str, float]) -> float | None:
    """Equal-weight directional return: long * +ret, short * -ret. Observe/skip (dir=0) excluded."""
    signed: list[float] = []
    for it in items or []:
        sym = str(it.get("sym") or "").upper()
        d = int(it.get("dir") or 0)
        ret = outcomes.get(sym)
        if ret is None or d == 0:
            continue
        signed.append(ret * d)
    if not signed:
        return None
    return round(sum(signed) / len(signed), 6)


def _paired_display_dates(chain: str, *, days: int = 30) -> list[str]:
    """Rolling display window — void-symmetric paired dates only (display-only, not verdict)."""
    from premarket_ab_pairing import is_either_side_void, paired_scorable_dates

    paired = paired_scorable_dates(limit=days, for_verdict=False)
    from premarket_ab_clock import is_scorable_day
    from premarket_ab_journal import STATS_GRID, STATS_SONNET, _load_stats

    path = STATS_GRID if chain == "grid" else STATS_SONNET
    all_stats = _load_stats(path)
    return [
        d
        for d in paired
        if d in all_stats
        and isinstance(all_stats.get(d), dict)
        and all_stats[d].get("return_pct") is not None
        and not is_either_side_void(d)
        and is_scorable_day(d)
    ]


def rolling_return_pct(chain: str, *, days: int = 30) -> float | None:
    """Display-only rolling sum over void-symmetric paired scorable days."""
    from premarket_ab_journal import STATS_GRID, STATS_SONNET, _load_stats

    path = STATS_GRID if chain == "grid" else STATS_SONNET
    all_stats = _load_stats(path)
    dated = _paired_display_dates(chain, days=days)
    if not dated:
        return None
    tail = [float(all_stats[d]["return_pct"]) for d in dated if all_stats[d].get("return_pct") is not None]
    return round(sum(tail), 6) if tail else None


def rolling_scorable_days(chain: str, *, days: int = 30) -> int:
    """Display-only paired scorable day count (grid_n == sonnet_n)."""
    from premarket_ab_pairing import assert_paired_symmetry

    dated = _paired_display_dates(chain, days=days)
    assert_paired_symmetry(dated)
    return len(dated)


def rolling_win_rate(chain: str, *, days: int = 30) -> dict[str, int | float | None]:
    """Display-only rolling win rate; denominator = directional signals only (wins+losses)."""
    from premarket_ab_journal import STATS_GRID, STATS_SONNET, _load_stats
    from premarket_ab_pairing import assert_paired_symmetry

    path = STATS_GRID if chain == "grid" else STATS_SONNET
    all_stats = _load_stats(path)
    dated = _paired_display_dates(chain, days=days)
    assert_paired_symmetry(dated)
    wins = sum(int(all_stats[d].get("wins") or 0) for d in dated)
    losses = sum(int(all_stats[d].get("losses") or 0) for d in dated)
    scored = wins + losses
    return {
        "wins": wins,
        "losses": losses,
        "n_scored": scored,
        "win_rate": round(wins / scored, 4) if scored else None,
        "window_days": len(dated),
        "display_only": True,
    }
