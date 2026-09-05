"""Off-pool A/B metrics — near-miss grounding and fabrication (硬凑) detection."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

NEAR_MISS_LINE = re.compile(r"Near-miss \(off-pool\):\s*(.+)", re.I)
NEAR_MISS_SYM = re.compile(r"\b([A-Z][A-Z0-9.\-]{0,9})\b score=")

_SP500_CACHE: set[str] | None = None


def sp500_symbols() -> set[str]:
    global _SP500_CACHE
    if _SP500_CACHE is not None:
        return _SP500_CACHE
    try:
        from aether_dryrun import get_sp500_universe

        df = get_sp500_universe()
        if df is not None and not df.empty and "symbol" in df.columns:
            _SP500_CACHE = {str(s).upper() for s in df["symbol"]}
        else:
            _SP500_CACHE = set()
    except Exception:
        _SP500_CACHE = set()
    return _SP500_CACHE


def near_miss_symbols_from_context(context: str) -> set[str]:
    """Symbols explicitly listed in the offpool prompt near-miss line."""
    for line in (context or "").splitlines():
        m = NEAR_MISS_LINE.search(line)
        if not m:
            continue
        return {s.upper() for s in NEAR_MISS_SYM.findall(m.group(1))}
    return set()


def near_miss_symbols_from_rejection_log(rej_path: Path, pool_syms: set[str]) -> set[str]:
    """All off-pool symbols with scores in rejection log (full file, no line cap)."""
    if not rej_path.is_file():
        return set()
    syms: set[str] = set()
    for ln in rej_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(ln)
        except json.JSONDecodeError:
            continue
        sym = str(row.get("symbol") or "").upper()
        if sym and sym not in pool_syms and row.get("score") is not None:
            syms.add(sym)
    return syms


def load_offpool_candidates(rej_path: Path, pool_syms: set[str], *, sp500_only: bool = True) -> list[dict[str, Any]]:
    """Quant-derived off-pool whitelist — best score row per symbol, full rejection log."""
    if not rej_path.is_file():
        return []
    # E-3: filter to S&P when available. Empty set means load failed — do not
    # silently wipe the entire whitelist (that is how ONTO/near-miss vanished
    # from prompts while looking like "no candidates").
    universe = sp500_symbols() if sp500_only else None
    if universe is not None and not universe:
        universe = None
    best: dict[str, dict[str, Any]] = {}
    for ln in rej_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(ln)
        except json.JSONDecodeError:
            continue
        sym = str(row.get("symbol") or "").upper()
        score = row.get("score")
        if not sym or sym in pool_syms or score is None:
            continue
        if universe is not None and sym not in universe:
            continue
        try:
            score_f = float(score)
        except (TypeError, ValueError):
            continue
        prev = best.get(sym)
        if prev is None or score_f > float(prev["score"]):
            best[sym] = {
                "sym": sym,
                "score": round(score_f, 2),
                "kill_rule": str(row.get("kill_rule") or ""),
            }
    return sorted(best.values(), key=lambda x: (-float(x["score"]), x["sym"]))


def grounded_emit_items(
    items: list[dict],
    *,
    near_miss_syms: set[str],
    pool_syms: set[str],
    candidate_syms: set[str] | None = None,
) -> tuple[list[dict], list[str]]:
    """Keep only whitelist-grounded, non-pool items for store/UI emit.

    H10: when ``candidate_syms`` is provided (the S&P500-filtered whitelist the
    model was prompted with), require the symbol to be in that set too — so a
    model output outside the prompt whitelist cannot pass grounding just because
    it happens to appear in the broader near-miss rejection log.
    """
    emit: list[dict] = []
    dropped: list[str] = []
    for item in items:
        sym = str(item.get("sym") or "").upper()
        if not sym:
            continue
        if sym in pool_syms:
            dropped.append(sym)
            continue
        if sym not in near_miss_syms:
            dropped.append(sym)
            continue
        if candidate_syms is not None and sym not in candidate_syms:
            dropped.append(f"{sym}:not_in_prompt_whitelist")
            continue
        emit.append(item)
    return emit, dropped


def assert_offpool_constitution(items: list[dict]) -> tuple[list[dict], list[str]]:
    """E-3: single-leg call lane — long (dir=1) or omit; no bearish/neutral tools."""
    kept: list[dict] = []
    dropped: list[str] = []
    for item in items:
        sym = str(item.get("sym") or "").upper()
        value = str(item.get("value") or "")
        dir_i = int(item.get("dir") or 0)
        if not sym:
            continue
        if "空" in value or dir_i < 0:
            dropped.append(f"{sym}:bearish")
            continue
        if dir_i != 1:
            dropped.append(f"{sym}:not_long(dir={dir_i})")
            continue
        kept.append(item)
    return kept, dropped


def store_stats_from_emit(
    emit_items: list[dict],
    *,
    near_miss_count: int,
    parse_ok: bool,
    **extra: Any,
) -> dict[str, Any]:
    """Stats attached to grid_store — no fabrication/hard_pad labels (audit stays in daemon log)."""
    stats: dict[str, Any] = {
        "item_count": len(emit_items),
        "near_miss_count": near_miss_count,
        "grounded_count": len(emit_items),
        "parse_ok": parse_ok,
    }
    stats.update(extra)
    return stats

def score_fabrication(
    items: list[dict],
    *,
    near_miss_syms: set[str],
    near_miss_count: int,
) -> dict[str, Any]:
    """Hard-pad (硬凑): item not grounded in near-miss set, or 3 items when <3 near-misses."""
    item_syms = [str(i.get("sym") or "").upper() for i in items if i.get("sym")]
    grounded = [s for s in item_syms if s in near_miss_syms]
    fabricated = [s for s in item_syms if s not in near_miss_syms]
    item_count = len(item_syms)
    fabricated_count = len(fabricated)
    padded_to_three = item_count >= 3 and near_miss_count < 3
    return {
        "near_miss_count": near_miss_count,
        "grounded_count": len(grounded),
        "fabricated_count": fabricated_count,
        "fabricated_syms": fabricated,
        "fabrication_rate": round(fabricated_count / item_count, 3) if item_count else 0.0,
        "padded_to_three": padded_to_three,
        "hard_pad": fabricated_count > 0 or padded_to_three,
    }


def aggregate_lane_week(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize one lane over multiple daily traces."""
    days = len(traces)
    if not days:
        return {"days": 0}
    total_items = 0
    total_in_pool = 0
    total_fabricated = 0
    hard_pad_days = 0
    padded_three_days = 0
    total_cost = 0.0
    parse_fail_days = 0
    daily: list[dict[str, Any]] = []

    for tr in sorted(traces, key=lambda x: x.get("trade_date") or ""):
        stats = tr.get("stats") or {}
        audit = tr.get("audit") or {}
        items = tr.get("items") or []
        raw_items = tr.get("items_raw") or items
        ic = stats.get("item_count", len(items))
        fab = audit.get("fabricated_count")
        if fab is None:
            fab = stats.get("fabricated_count")
        if fab is None:
            fab_stats = score_fabrication(
                raw_items,
                near_miss_syms=set(audit.get("near_miss_syms") or stats.get("near_miss_syms") or []),
                near_miss_count=int(audit.get("near_miss_count") or stats.get("near_miss_count") or 0),
            )
            fab = fab_stats["fabricated_count"]
            hard = fab_stats["hard_pad"]
            pad3 = fab_stats["padded_to_three"]
        else:
            hard = bool(audit.get("hard_pad") if audit else stats.get("hard_pad"))
            pad3 = bool(audit.get("padded_to_three") if audit else stats.get("padded_to_three"))

        total_items += ic
        total_in_pool += int(stats.get("in_pool_count") or 0)
        total_fabricated += int(fab or 0)
        if hard:
            hard_pad_days += 1
        if pad3:
            padded_three_days += 1
        if not stats.get("parse_ok", True) and ic == 0:
            parse_fail_days += 1
        cost = stats.get("cost_usd")
        if cost is not None:
            total_cost += float(cost)

        daily.append(
            {
                "trade_date": tr.get("trade_date"),
                "item_count": ic,
                "in_pool_count": stats.get("in_pool_count", 0),
                "fabricated_count": fab,
                "fabricated_syms": stats.get("fabricated_syms") or [],
                "hard_pad": hard,
                "padded_to_three": pad3,
                "cost_usd": cost,
            }
        )

    return {
        "days": days,
        "total_items": total_items,
        "total_in_pool": total_in_pool,
        "in_pool_rate": round(total_in_pool / total_items, 3) if total_items else 0.0,
        "total_fabricated": total_fabricated,
        "fabrication_rate": round(total_fabricated / total_items, 3) if total_items else 0.0,
        "hard_pad_days": hard_pad_days,
        "hard_pad_day_rate": round(hard_pad_days / days, 3),
        "padded_to_three_days": padded_three_days,
        "parse_fail_days": parse_fail_days,
        "total_cost_usd": round(total_cost, 4),
        "avg_cost_usd": round(total_cost / days, 4) if days else 0.0,
        "daily": daily,
    }
