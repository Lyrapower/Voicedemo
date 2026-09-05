"""Daily premarket A/B summary for post-market 复盘 — chains never merged."""
from __future__ import annotations

from typing import Any

from premarket_ab_divergence import (
    fetch_premarket_from_store,
    find_divergences,
    items_by_sym,
)
from premarket_ab_journal import is_context_asymmetric, reconcile_chain
from premarket_ab_clock import AB_LEDGER_START_DATE, ab_ledger_meta
from premarket_ab_returns import (
    chain_signed_return_pct,
    fetch_day_returns,
    rolling_return_pct,
    rolling_scorable_days,
    rolling_win_rate,
)


def _fmt_win_rate(wr: dict[str, int | float | None] | None, *, before_start: bool = False) -> str:
    if before_start:
        return f"起算 {AB_LEDGER_START_DATE[5:]}"
    if not wr or wr.get("win_rate") is None:
        return "—"
    return f"{wr['win_rate']:.0%} ({wr.get('wins', 0)}/{wr.get('n_scored', 0)})"


def _fmt_pct(v: float | None, *, before_start: bool = False) -> str:
    if before_start:
        return f"起算 {AB_LEDGER_START_DATE[5:]}"
    if v is None:
        return "—"
    return f"{v * 100:+.2f}%"


def _aligned_count(grid_items: list[dict[str, Any]], sonnet_items: list[dict[str, Any]]) -> int:
    gmap = items_by_sym(grid_items)
    smap = items_by_sym(sonnet_items)
    syms = set(gmap) & set(smap)
    div_syms = {d["sym"] for d in find_divergences(grid_items, sonnet_items)}
    return len(syms) - len(div_syms)


def build_premarket_ab_summary(
    trade_date: str,
    *,
    outcomes: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Structured A/B snapshot — Grid / Sonnet stats independent."""
    grid_items = fetch_premarket_from_store(kind="aether_premarket_grid", trade_date=trade_date)
    sonnet_items = fetch_premarket_from_store(kind="aether_premarket_sonnet", trade_date=trade_date)
    syms = {
        str(it.get("sym") or "").upper()
        for it in grid_items + sonnet_items
        if it.get("sym")
    }
    if outcomes is None:
        outcomes = fetch_day_returns(trade_date, syms)
    divergences = find_divergences(grid_items, sonnet_items)
    grid_stats = reconcile_chain("grid", trade_date, outcomes=outcomes)
    sonnet_stats = reconcile_chain("sonnet", trade_date, outcomes=outcomes)
    grid_ret = grid_stats.get("return_pct")
    if grid_ret is None:
        grid_ret = chain_signed_return_pct(grid_items, outcomes)
    sonnet_ret = sonnet_stats.get("return_pct")
    if sonnet_ret is None:
        sonnet_ret = chain_signed_return_pct(sonnet_items, outcomes)
    aligned = _aligned_count(grid_items, sonnet_items)
    asymmetric = is_context_asymmetric(trade_date)
    void_reason = (grid_stats.get("context_asymmetric_reason") or sonnet_stats.get("context_asymmetric_reason"))
    clock = ab_ledger_meta(trade_date, void=asymmetric)
    g30 = rolling_return_pct("grid") if clock["scorable"] else None
    s30 = rolling_return_pct("sonnet") if clock["scorable"] else None
    g_wr30 = rolling_win_rate("grid") if clock["scorable"] else None
    s_wr30 = rolling_win_rate("sonnet") if clock["scorable"] else None
    return {
        "date": trade_date,
        "grid_n": len(grid_items),
        "sonnet_n": len(sonnet_items),
        "aligned_n": aligned,
        "divergence_n": len(divergences),
        "divergences": divergences[:12],
        "grid_stats": grid_stats,
        "sonnet_stats": sonnet_stats,
        "grid_return_pct": grid_ret,
        "sonnet_return_pct": sonnet_ret,
        "grid_return_30d_pct": g30,
        "sonnet_return_30d_pct": s30,
        "grid_rolling_win_rate": g_wr30,
        "sonnet_rolling_win_rate": s_wr30,
        "grid_scorable_days_30d": rolling_scorable_days("grid") if clock["scorable"] else 0,
        "sonnet_scorable_days_30d": rolling_scorable_days("sonnet") if clock["scorable"] else 0,
        "ab_ledger_start": AB_LEDGER_START_DATE,
        "warmup": clock["warmup"],
        "scorable": clock["scorable"],
        "context_asymmetric": asymmetric,
        "context_asymmetric_reason": void_reason if asymmetric else None,
        "ab_void": asymmetric,
        "outcomes_n": len(outcomes or {}),
        "report_only": True,
        "note": "30d A/B · 账本独立 · 不据单日调权重"
        + (f" · warmup · 30d 起算 {AB_LEDGER_START_DATE}" if clock["warmup"] else ""),
    }


def format_premarket_ab_brief_text(summary: dict[str, Any]) -> str:
    if not summary.get("grid_n") and not summary.get("sonnet_n"):
        return ""
    d = summary.get("date") or ""
    gs = summary.get("grid_stats") or {}
    ss = summary.get("sonnet_stats") or {}
    g_ret = summary.get("grid_return_pct")
    s_ret = summary.get("sonnet_return_pct")
    g30 = summary.get("grid_return_30d_pct")
    s30 = summary.get("sonnet_return_30d_pct")
    gwr = summary.get("grid_rolling_win_rate") or {}
    swr = summary.get("sonnet_rolling_win_rate") or {}
    warmup = bool(summary.get("warmup"))
    lines = [
        f"盘前 A/B · {d}",
    ]
    if summary.get("context_asymmetric"):
        reason = summary.get("context_asymmetric_reason") or "context_asymmetric"
        lines.append(f"VOID · 今日对比不算数 · {reason}")
    lines += [
        f"GRID {summary.get('grid_n', 0)} 条 · 当日收益 {_fmt_pct(g_ret)}"
        + (f" · 胜率 {gs.get('win_rate', 0):.0%} ({gs.get('wins', 0)}/{gs.get('wins', 0)+gs.get('losses', 0)})"
           if (gs.get("wins", 0) + gs.get("losses", 0)) else ""),
        f"SONNET {summary.get('sonnet_n', 0)} 条 · 当日收益 {_fmt_pct(s_ret)}"
        + (f" · 胜率 {ss.get('win_rate', 0):.0%} ({ss.get('wins', 0)}/{ss.get('wins', 0)+ss.get('losses', 0)})"
           if (ss.get("wins", 0) + ss.get("losses", 0)) else ""),
        f"30d 累计 · GRID {_fmt_pct(g30, before_start=warmup)} · SONNET {_fmt_pct(s30, before_start=warmup)}"
        + f" · 30d胜率 GRID {_fmt_win_rate(gwr, before_start=warmup)} · SONNET {_fmt_win_rate(swr, before_start=warmup)}"
        + (f" · warmup · 正式起算 {AB_LEDGER_START_DATE}" if warmup else "")
        + f" · 可计日 grid={summary.get('grid_scorable_days_30d', 0)} sonnet={summary.get('sonnet_scorable_days_30d', 0)}",
    ]
    return "\n".join(lines)


def premarket_ab_brief_items(summary: dict[str, Any]) -> list[dict[str, Any]]:
    if not summary.get("grid_n") and not summary.get("sonnet_n"):
        return []
    items: list[dict[str, Any]] = []
    gs = summary.get("grid_stats") or {}
    ss = summary.get("sonnet_stats") or {}
    g_ret = summary.get("grid_return_pct")
    s_ret = summary.get("sonnet_return_pct")
    gwr = summary.get("grid_rolling_win_rate") or {}
    swr = summary.get("sonnet_rolling_win_rate") or {}
    void_note = "VOID · 不算数" if summary.get("context_asymmetric") else None
    g_wr_s = _fmt_win_rate(gwr) if gwr.get("win_rate") is not None else None
    s_wr_s = _fmt_win_rate(swr) if swr.get("win_rate") is not None else None
    items.append({
        "sym": "—",
        "label": "ab_grid",
        "value": f"当日 {_fmt_pct(g_ret)} · 30d {_fmt_pct(summary.get('grid_return_30d_pct'))}",
        "note": void_note or (
            f"{summary.get('grid_n', 0)} 条 · 当日胜率 {gs.get('win_rate', 0):.0%}"
            + (f" · 30d {g_wr_s}" if g_wr_s else "")
            if gs.get("n_items") else "report-only"
        ),
        "dir": 1 if (g_ret or 0) > 0 else -1 if (g_ret or 0) < 0 else 0,
        "src": "premarket_ab",
    })
    items.append({
        "sym": "—",
        "label": "ab_sonnet",
        "value": f"当日 {_fmt_pct(s_ret)} · 30d {_fmt_pct(summary.get('sonnet_return_30d_pct'))}",
        "note": void_note or (
            f"{summary.get('sonnet_n', 0)} 条 · 当日胜率 {ss.get('win_rate', 0):.0%}"
            + (f" · 30d {s_wr_s}" if s_wr_s else "")
            if ss.get("n_items") else "report-only"
        ),
        "dir": 1 if (s_ret or 0) > 0 else -1 if (s_ret or 0) < 0 else 0,
        "src": "premarket_ab",
    })
    return items
