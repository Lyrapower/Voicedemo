"""Daily DeepSeek vs Sonnet performance — post-market report-only (5d observation)."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from premarket_ab_divergence import fetch_premarket_from_store, items_by_sym
from offpool_ab_stats import aggregate_lane_week

REPO_ROOT = Path(__file__).resolve().parent.parent
TRACE_DIR = REPO_ROOT / "grid-sovereign-runtime" / "traces" / "daemon"
OBSERVATION_DAYS = 5
OFFPOOL_LANES = ("sonnet-4.6", "deepseek-v4")
PREMARKET_WINDOWS = ("premarket", "intraday")


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def load_offpool_trace(lane: str, trade_date: dt.date) -> dict[str, Any] | None:
    return _read_json(TRACE_DIR / f"offpool_{lane}_{trade_date.isoformat()}.json")


def load_premarket_deepseek_trace(window: str, trade_date: dt.date) -> dict[str, Any] | None:
    return _read_json(TRACE_DIR / f"premarket_deepseek_{window}_{trade_date.isoformat()}.json")


def load_offpool_traces_range(lane: str, *, since: dt.date, until: dt.date) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    d = since
    while d <= until:
        row = load_offpool_trace(lane, d)
        if row and not row.get("test_mode"):
            out.append(row)
        d += dt.timedelta(days=1)
    return out


def _fmt_duration_ms(ms: int | float | None) -> str:
    if ms is None:
        return "—"
    sec = float(ms) / 1000.0
    if sec >= 60:
        return f"{sec / 60:.1f}m"
    return f"{sec:.1f}s"


def _fmt_rate(rate: float | None) -> str:
    if rate is None:
        return "—"
    return f"{rate * 100:.1f}%"


def _day_from_offpool_trace(trace: dict[str, Any]) -> dict[str, Any]:
    stats = trace.get("stats") or {}
    audit = trace.get("audit") or {}
    items = trace.get("items") or []
    ic = int(stats.get("item_count") or len(items))
    fab = audit.get("fabricated_count")
    if fab is None:
        fab = stats.get("fabricated_count", 0)
    fab_rate = audit.get("fabrication_rate")
    if fab_rate is None and ic:
        fab_rate = round(int(fab or 0) / ic, 3)
    return {
        "lane": trace.get("lane"),
        "item_count": ic,
        "fabricated_count": int(fab or 0),
        "fabrication_rate": fab_rate,
        "hard_pad": bool(audit.get("hard_pad")),
        "in_pool_count": int(stats.get("in_pool_count") or 0),
        "duration_ms": stats.get("duration_ms"),
        "cost_usd": stats.get("cost_usd"),
        "parse_ok": bool(stats.get("parse_ok", True)),
        "syms": [str(i.get("sym") or "").upper() for i in items if i.get("sym")],
        "error": trace.get("error"),
        "missing": False,
    }


def _day_from_premarket_trace(trace: dict[str, Any]) -> dict[str, Any]:
    items = trace.get("items") or []
    meta = trace.get("meta") or {}
    return {
        "window": trace.get("window"),
        "window_label": trace.get("window_label"),
        "item_count": len(items),
        "syms": [str(i.get("sym") or "").upper() for i in items if i.get("sym")],
        "duration_ms": meta.get("duration_ms"),
        "error": meta.get("error"),
        "missing": False,
    }


def _compare_offpool_day(
    sonnet: dict[str, Any] | None,
    deepseek: dict[str, Any] | None,
) -> dict[str, Any]:
    sn = sonnet or {}
    ds = deepseek or {}
    if sn.get("missing") and ds.get("missing"):
        return {"status": "no_data"}
    sn_syms = set(sn.get("syms") or [])
    ds_syms = set(ds.get("syms") or [])
    overlap = sorted(sn_syms & ds_syms)
    sn_ms = sn.get("duration_ms")
    ds_ms = ds.get("duration_ms")
    faster = None
    if sn_ms is not None and ds_ms is not None:
        faster = "deepseek" if ds_ms < sn_ms else "sonnet" if sn_ms < ds_ms else "tie"
    sn_fab = int(sn.get("fabricated_count") or 0)
    ds_fab = int(ds.get("fabricated_count") or 0)
    cleaner = None
    if not sn.get("missing") and not ds.get("missing"):
        if ds_fab < sn_fab:
            cleaner = "deepseek"
        elif sn_fab < ds_fab:
            cleaner = "sonnet"
        else:
            cleaner = "tie"
    return {
        "status": "ok",
        "sym_overlap": overlap,
        "sym_overlap_n": len(overlap),
        "faster_lane": faster,
        "cleaner_lane": cleaner,
        "sonnet_fabricated": sn_fab,
        "deepseek_fabricated": ds_fab,
    }


def _aggregate_premarket_deepseek(*, since: dt.date, until: dt.date) -> dict[str, Any]:
    by_window: dict[str, list[dict[str, Any]]] = {w: [] for w in PREMARKET_WINDOWS}
    d = since
    while d <= until:
        for win in PREMARKET_WINDOWS:
            tr = load_premarket_deepseek_trace(win, d)
            if tr and not tr.get("test_mode"):
                by_window[win].append(_day_from_premarket_trace(tr))
        d += dt.timedelta(days=1)
    rolling: dict[str, Any] = {}
    for win, days in by_window.items():
        if not days:
            rolling[win] = {"days": 0}
            continue
        total_items = sum(int(x.get("item_count") or 0) for x in days)
        durations = [x.get("duration_ms") for x in days if x.get("duration_ms") is not None]
        rolling[win] = {
            "days": len(days),
            "total_items": total_items,
            "avg_items": round(total_items / len(days), 2),
            "avg_duration_ms": round(sum(durations) / len(durations), 1) if durations else None,
        }
    return rolling


def _has_any_data(summary: dict[str, Any]) -> bool:
    off = summary.get("offpool") or {}
    pre = summary.get("premarket") or {}
    daily_off = off.get("daily") or {}
    daily_pre = pre.get("daily") or {}
    for lane in OFFPOOL_LANES:
        row = daily_off.get(lane) or {}
        if not row.get("missing"):
            return True
    for win in PREMARKET_WINDOWS:
        row = daily_pre.get(win) or {}
        if not row.get("missing"):
            return True
    return False


def build_deepseek_performance_summary(trade_date: str) -> dict[str, Any]:
    """Structured DeepSeek vs Sonnet snapshot — report-only, 5d rolling."""
    td = dt.date.fromisoformat(trade_date)
    since = td - dt.timedelta(days=OBSERVATION_DAYS - 1)

    offpool_daily: dict[str, Any] = {}
    for lane in OFFPOOL_LANES:
        tr = load_offpool_trace(lane, td)
        offpool_daily[lane] = _day_from_offpool_trace(tr) if tr else {"missing": True, "lane": lane}

    premarket_daily: dict[str, Any] = {}
    for win in PREMARKET_WINDOWS:
        tr = load_premarket_deepseek_trace(win, td)
        premarket_daily[win] = _day_from_premarket_trace(tr) if tr else {"missing": True, "window": win}

    sonnet_legacy_items = fetch_premarket_from_store(kind="aether_premarket_sonnet", trade_date=trade_date)
    ds_legacy_overlap = 0
    ds_syms: set[str] = set()
    for win in PREMARKET_WINDOWS:
        ds_syms.update(premarket_daily.get(win, {}).get("syms") or [])
    if sonnet_legacy_items:
        smap = items_by_sym(sonnet_legacy_items)
        ds_legacy_overlap = len(set(smap) & ds_syms)

    rolling_offpool: dict[str, Any] = {}
    for lane in OFFPOOL_LANES:
        traces = load_offpool_traces_range(lane, since=since, until=td)
        rolling_offpool[lane] = aggregate_lane_week(traces)

    comparison = _compare_offpool_day(
        offpool_daily.get("sonnet-4.6"),
        offpool_daily.get("deepseek-v4"),
    )

    return {
        "date": trade_date,
        "report_only": True,
        "observation_days": OBSERVATION_DAYS,
        "observation_since": since.isoformat(),
        "offpool": {
            "daily": offpool_daily,
            "comparison": comparison,
            "rolling": rolling_offpool,
        },
        "premarket": {
            "daily": premarket_daily,
            "sonnet_legacy_n": len(sonnet_legacy_items),
            "sonnet_legacy_overlap_n": ds_legacy_overlap,
            "rolling": _aggregate_premarket_deepseek(since=since, until=td),
        },
        "note": f"{OBSERVATION_DAYS}d观察 · report-only · 不触发 learning unlock",
    }


def _offpool_lane_line(label: str, row: dict[str, Any]) -> str:
    if row.get("missing"):
        return f"  {label} —"
    parts = [f"{row.get('item_count', 0)}条"]
    fab = int(row.get("fabricated_count") or 0)
    parts.append(f"硬凑{fab}")
    in_pool = int(row.get("in_pool_count") or 0)
    if in_pool:
        parts.append(f"in_pool{in_pool}")
    dur = _fmt_duration_ms(row.get("duration_ms"))
    if dur != "—":
        parts.append(dur)
    cost = row.get("cost_usd")
    if cost is not None:
        parts.append(f"${float(cost):.3f}")
    if row.get("error"):
        parts.append(f"err={row['error']}")
    return f"  {label} " + " · ".join(parts)


def format_deepseek_performance_text(summary: dict[str, Any]) -> str:
    if not _has_any_data(summary):
        return ""
    d = summary.get("date") or ""
    lines = [f"DeepSeek 表现 · {d} (report-only · {OBSERVATION_DAYS}d观察)"]

    off = summary.get("offpool") or {}
    daily_off = off.get("daily") or {}
    sn = daily_off.get("sonnet-4.6") or {}
    ds = daily_off.get("deepseek-v4") or {}
    if not sn.get("missing") or not ds.get("missing"):
        lines.append("Off-pool · Sonnet vs DeepSeek:")
        lines.append(_offpool_lane_line("SN", sn))
        lines.append(_offpool_lane_line("DS", ds))
        cmp_ = off.get("comparison") or {}
        if cmp_.get("status") == "ok":
            hints: list[str] = []
            if cmp_.get("sym_overlap_n"):
                hints.append(f"重合{cmp_['sym_overlap_n']}")
            if cmp_.get("faster_lane") and cmp_["faster_lane"] != "tie":
                hints.append(f"更快={cmp_['faster_lane']}")
            if cmp_.get("cleaner_lane") and cmp_["cleaner_lane"] != "tie":
                hints.append(f"更净={cmp_['cleaner_lane']}")
            if hints:
                lines.append("  " + " · ".join(hints))

    pre = summary.get("premarket") or {}
    daily_pre = pre.get("daily") or {}
    pre_lines: list[str] = []
    for win in PREMARKET_WINDOWS:
        row = daily_pre.get(win) or {}
        if row.get("missing"):
            continue
        label = row.get("window_label") or win
        dur = _fmt_duration_ms(row.get("duration_ms"))
        pre_lines.append(f"  {label} {row.get('item_count', 0)}条 · {dur}")
    if pre_lines:
        lines.append("盘前 DeepSeek:")
        lines.extend(pre_lines)
    legacy_n = int(pre.get("sonnet_legacy_n") or 0)
    if legacy_n and pre_lines:
        overlap = int(pre.get("sonnet_legacy_overlap_n") or 0)
        lines.append(f"  legacy Sonnet {legacy_n}条 · 与 DS 重合 {overlap}")

    rolling = off.get("rolling") or {}
    sn_roll = rolling.get("sonnet-4.6") or {}
    ds_roll = rolling.get("deepseek-v4") or {}
    if (sn_roll.get("days") or 0) or (ds_roll.get("days") or 0):
        lines.append(
            f"{OBSERVATION_DAYS}d off-pool · "
            f"DS 硬凑率 {_fmt_rate(ds_roll.get('fabrication_rate'))} ({ds_roll.get('days', 0)}天) · "
            f"SN 硬凑率 {_fmt_rate(sn_roll.get('fabrication_rate'))} ({sn_roll.get('days', 0)}天)"
        )
        ds_avg = ds_roll.get("avg_cost_usd")
        sn_avg = sn_roll.get("avg_cost_usd")
        if sn_avg:
            lines[-1] += f" · SN avg ${sn_avg:.3f}/天"

    return "\n".join(lines)


def deepseek_performance_brief_items(summary: dict[str, Any]) -> list[dict[str, Any]]:
    if not _has_any_data(summary):
        return []
    items: list[dict[str, Any]] = []
    off = summary.get("offpool") or {}
    daily_off = off.get("daily") or {}
    ds = daily_off.get("deepseek-v4") or {}
    sn = daily_off.get("sonnet-4.6") or {}
    if not ds.get("missing") or not sn.get("missing"):
        ds_fab = int(ds.get("fabricated_count") or 0)
        sn_fab = int(sn.get("fabricated_count") or 0)
        note_parts = [
            f"DS {ds.get('item_count', 0)}条 硬凑{ds_fab} {_fmt_duration_ms(ds.get('duration_ms'))}",
            f"SN {sn.get('item_count', 0)}条 硬凑{sn_fab} {_fmt_duration_ms(sn.get('duration_ms'))}",
        ]
        cost = sn.get("cost_usd")
        if cost is not None:
            note_parts[-1] += f" ${float(cost):.3f}"
        items.append(
            {
                "sym": "—",
                "label": "ds_offpool",
                "value": "off-pool DS vs SN",
                "note": " · ".join(note_parts),
                "dir": 1 if ds_fab < sn_fab else -1 if ds_fab > sn_fab else 0,
                "src": "deepseek_performance",
            }
        )
    pre = summary.get("premarket") or {}
    daily_pre = pre.get("daily") or {}
    win_bits: list[str] = []
    for win in PREMARKET_WINDOWS:
        row = daily_pre.get(win) or {}
        if row.get("missing"):
            continue
        win_bits.append(f"{win}={row.get('item_count', 0)}")
    if win_bits:
        items.append(
            {
                "sym": "—",
                "label": "ds_premarket",
                "value": "盘前 DeepSeek",
                "note": " · ".join(win_bits),
                "dir": 0,
                "src": "deepseek_performance",
            }
        )
    rolling = off.get("rolling") or {}
    ds_roll = rolling.get("deepseek-v4") or {}
    if ds_roll.get("days"):
        items.append(
            {
                "sym": "—",
                "label": "ds_5d",
                "value": f"{OBSERVATION_DAYS}d off-pool DS",
                "note": (
                    f"硬凑率 {_fmt_rate(ds_roll.get('fabrication_rate'))} · "
                    f"{ds_roll.get('days', 0)}天 · {ds_roll.get('total_items', 0)}条"
                ),
                "dir": 0,
                "src": "deepseek_performance",
            }
        )
    return items
