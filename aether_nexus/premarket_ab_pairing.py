"""Paired A/B ledger — void symmetry, verdict window, information bucket."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from premarket_ab_clock import AB_LEDGER_START_DATE, is_scorable_day, is_warmup_day
from premarket_ab_journal import (
    JOURNAL_GRID,
    JOURNAL_SONNET,
    STATS_GRID,
    STATS_SONNET,
    _load_stats,
)

VERDICT_WINDOW_DAYS = 30


def _journal_path(chain: Literal["grid", "sonnet"]) -> Path:
    return JOURNAL_GRID if chain == "grid" else JOURNAL_SONNET


def journal_rows_for_date(trade_date: str, chain: Literal["grid", "sonnet"]) -> list[dict[str, Any]]:
    path = _journal_path(chain)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("date") == trade_date:
            rows.append(row)
    return rows


def is_directional_row(row: dict[str, Any]) -> bool:
    """Win-rate / return denominator: directional signals only (observe/skip excluded)."""
    return int(row.get("dir") or 0) != 0


def row_attribution(row: dict[str, Any]) -> str:
    raw = row.get("attribution")
    if raw:
        return str(raw).lower()
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    return str(meta.get("attribution") or "").lower()


def is_information_bucket_row(row: dict[str, Any], grid_directional_syms: set[str]) -> bool:
    """Sonnet-only ∩ info_basis=world-knowledge ∩ attribution=information."""
    sym = str(row.get("sym") or "").upper()
    if not sym or sym in grid_directional_syms:
        return False
    basis = str(row.get("info_basis") or "").lower()
    if basis != "world-knowledge":
        return False
    return row_attribution(row) == "information"


def chain_equal_weight_return(
    rows: list[dict[str, Any]],
    outcomes: dict[str, float],
    *,
    exclude: set[tuple[str, int]] | None = None,
) -> tuple[float | None, int]:
    """Equal-weight signed return over directional rows; exclude keyed by (sym, dir)."""
    exclude = exclude or set()
    signed: list[float] = []
    for row in rows:
        if not is_directional_row(row):
            continue
        sym = str(row.get("sym") or "").upper()
        d = int(row.get("dir") or 0)
        if (sym, d) in exclude:
            continue
        ret = outcomes.get(sym)
        if ret is None:
            continue
        signed.append(ret * d)
    if not signed:
        return None, 0
    return round(sum(signed) / len(signed), 6), len(signed)


def daily_returns_for_date(
    trade_date: str,
    outcomes: dict[str, float],
    *,
    adjusted: bool = False,
) -> tuple[float | None, float | None]:
    """(grid_return, sonnet_return) for one trade date; sonnet adjusted excludes info bucket."""
    grid_rows = journal_rows_for_date(trade_date, "grid")
    sonnet_rows = journal_rows_for_date(trade_date, "sonnet")
    grid_dir_syms = {str(r.get("sym") or "").upper() for r in grid_rows if is_directional_row(r)}
    g_ret, _ = chain_equal_weight_return(grid_rows, outcomes)
    if not adjusted:
        s_ret, _ = chain_equal_weight_return(sonnet_rows, outcomes)
        return g_ret, s_ret
    exclude: set[tuple[str, int]] = set()
    for row in sonnet_rows:
        if is_information_bucket_row(row, grid_dir_syms):
            sym = str(row.get("sym") or "").upper()
            exclude.add((sym, int(row.get("dir") or 0)))
    s_ret, _ = chain_equal_weight_return(sonnet_rows, outcomes, exclude=exclude)
    return g_ret, s_ret


def is_either_side_void(trade_date: str) -> bool:
    """Either-side void → exclude from paired scorable set (both chains)."""
    if is_warmup_day(trade_date):
        return True
    for path in (STATS_GRID, STATS_SONNET):
        entry = _load_stats(path).get(trade_date)
        if not isinstance(entry, dict):
            continue
        if entry.get("context_asymmetric") or entry.get("ab_void"):
            return True
    return False


def paired_scorable_dates(*, limit: int | None = VERDICT_WINDOW_DAYS, for_verdict: bool = False) -> list[str]:
    """Paired scorable trading days ≥ ledger start; void-symmetric; grid_n == sonnet_n by construction."""
    g = _load_stats(STATS_GRID)
    s = _load_stats(STATS_SONNET)
    candidates = sorted(set(g) & set(s))
    dates: list[str] = []
    for d in candidates:
        if not is_scorable_day(d):
            continue
        if is_either_side_void(d):
            continue
        gv = g.get(d) if isinstance(g.get(d), dict) else {}
        sv = s.get(d) if isinstance(s.get(d), dict) else {}
        if gv.get("return_pct") is None or sv.get("return_pct") is None:
            continue
        dates.append(d)
    assert_paired_symmetry(dates)
    if limit is not None and len(dates) > limit:
        if for_verdict:
            # Fixed 30 trading-day verdict window anchored at ledger start (most recent 30 within epoch)
            dates = dates[-limit:]
        else:
            dates = dates[-limit:]
    return dates


def assert_paired_symmetry(dates: list[str]) -> None:
    """grid_n == sonnet_n: each paired date counts once for both chains."""
    g = _load_stats(STATS_GRID)
    s = _load_stats(STATS_SONNET)
    grid_n = sum(1 for d in dates if isinstance(g.get(d), dict) and g[d].get("return_pct") is not None)
    sonnet_n = sum(1 for d in dates if isinstance(s.get(d), dict) and s[d].get("return_pct") is not None)
    assert grid_n == sonnet_n == len(dates), f"paired scorable mismatch grid={grid_n} sonnet={sonnet_n} dates={len(dates)}"


def outcomes_from_stats(trade_date: str) -> dict[str, float]:
    """Stored sym→return from stats ledger (grid or sonnet)."""
    for path in (STATS_GRID, STATS_SONNET):
        stored = (_load_stats(path).get(trade_date) or {}).get("outcomes")
        if isinstance(stored, dict) and stored:
            return {str(k).upper(): float(v) for k, v in stored.items()}
    return {}


def paired_daily_diffs(
    *,
    adjusted: bool = False,
    for_verdict: bool = True,
    limit: int | None = VERDICT_WINDOW_DAYS,
) -> list[tuple[str, float]]:
    """Bootstrap input: paired day (sonnet − grid) diffs on void-symmetric scorable dates."""
    g = _load_stats(STATS_GRID)
    s = _load_stats(STATS_SONNET)
    dates = paired_scorable_dates(limit=limit, for_verdict=for_verdict)
    diffs: list[tuple[str, float]] = []
    for d in dates:
        gv = g.get(d) if isinstance(g.get(d), dict) else {}
        sv = s.get(d) if isinstance(s.get(d), dict) else {}
        outcomes = gv.get("outcomes") or sv.get("outcomes") or {}
        if isinstance(outcomes, dict) and outcomes:
            gr, sr = daily_returns_for_date(d, {str(k).upper(): float(v) for k, v in outcomes.items()}, adjusted=adjusted)
        else:
            gr = gv.get("return_pct")
            if adjusted:
                sr = sv.get("adjusted_return_pct")
                if sr is None:
                    sr = sv.get("return_pct")
            else:
                sr = sv.get("return_pct")
        if gr is None or sr is None:
            continue
        diffs.append((d, float(sr) - float(gr)))
    assert len(diffs) == len(dates), f"paired diff incomplete {len(diffs)}/{len(dates)}"
    return diffs


def cumulative_paired_returns(*, adjusted: bool = False, for_verdict: bool = True) -> tuple[float, float]:
    """Sum grid/sonnet returns over paired scorable window."""
    diffs_data = paired_daily_diffs(adjusted=adjusted, for_verdict=for_verdict)
    if not diffs_data:
        return 0.0, 0.0
    g = _load_stats(STATS_GRID)
    s = _load_stats(STATS_SONNET)
    dates = [d for d, _ in diffs_data]
    grid_sum = sum(float((g.get(d) or {}).get("return_pct") or 0) for d in dates)
    if adjusted:
        sonnet_sum = sum(
            float((s.get(d) or {}).get("adjusted_return_pct") or (s.get(d) or {}).get("return_pct") or 0)
            for d in dates
        )
    else:
        sonnet_sum = sum(float((s.get(d) or {}).get("return_pct") or 0) for d in dates)
    return round(grid_sum, 6), round(sonnet_sum, 6)
