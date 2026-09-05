"""Shared pool-universe context for premarket A/B — Grid & Sonnet chains.

红线: 本模块只产出客观 pool/scan 上下文，禁止注入任一编译链的输出。
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pool_config import pool_symbols, pool_symbols_set

BASE_DIR = Path(__file__).resolve().parent
DRYRUN_STATE = BASE_DIR / "dryrun_state"
POOL_SIGNALS_PATH = DRYRUN_STATE / "pool_signals.json"
EST = ZoneInfo("America/New_York")

PREMARKET_FIVE_FIELD_SUFFIX = (
    "\n请按此格式输出3-5个候选，每条五字段（仅可从上方 pool 宇宙选标的）：\n"
    "标的：SYMBOL|方向：多/空/观察|为什么今天：（一句）|风险：（一句）|置信：[高置信/试探性/观察]\n"
    "规则：必须覆盖上方全宇宙表；不得只复读 top3；数据不全时宁可少给不可错给；"
    "缺核心因子的标的只给[观察]不给方向。"
)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _latest_signal_round(path: Path = POOL_SIGNALS_PATH) -> dict[str, Any]:
    data = _read_json(path, [])
    if isinstance(data, list) and data:
        last = data[-1]
        return last if isinstance(last, dict) else {}
    return {}


def _parse_scan_time(raw: str | None) -> dt.datetime | None:
    if not raw:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=EST)
    return parsed


def latest_pool_scan_round() -> dict[str, Any]:
    return _latest_signal_round()


def latest_pool_scan_date() -> str | None:
    scan_time = _parse_scan_time(latest_pool_scan_round().get("scan_time"))
    return scan_time.date().isoformat() if scan_time else None


def pool_scan_age_minutes(*, now: dt.datetime | None = None) -> float | None:
    scan_time = _parse_scan_time(latest_pool_scan_round().get("scan_time"))
    if scan_time is None:
        return None
    ref = now or dt.datetime.now(scan_time.tzinfo or EST)
    return max(0.0, (ref - scan_time).total_seconds() / 60.0)


def pool_scan_fresh(trade_date: dt.date, *, max_age_minutes: float = 150.0) -> bool:
    scan_date = latest_pool_scan_date()
    if scan_date != trade_date.isoformat():
        return False
    age = pool_scan_age_minutes()
    return age is not None and age <= max_age_minutes


def _pool_rows_from_rejection(rej_path: Path, pool_syms: set[str]) -> dict[str, dict[str, Any]]:
    if not rej_path.is_file():
        return {}
    best: dict[str, dict[str, Any]] = {}
    for ln in rej_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(ln)
        except json.JSONDecodeError:
            continue
        sym = str(row.get("symbol") or "").upper()
        if sym not in pool_syms:
            continue
        score = row.get("score")
        try:
            score_f = float(score) if score is not None else None
        except (TypeError, ValueError):
            score_f = None
        prev = best.get(sym)
        if prev is not None:
            prev_score = prev.get("score")
            if score_f is not None and prev_score is not None and score_f <= prev_score:
                continue
        best[sym] = {
            "symbol": sym,
            "score": score_f,
            "kill_rule": row.get("kill_rule") or row.get("reason"),
            "status": "filtered",
        }
    return best


def _format_score_row(sym: str, row: dict[str, Any] | None) -> str:
    if not row:
        return f"- {sym}: no scan row today (stage1/stage2 fail or no data)"
    status = row.get("status") or "unknown"
    score = row.get("score")
    score_txt = f"{float(score):.1f}" if score is not None else "—"
    if status == "passing":
        delta = row.get("delta")
        iv = row.get("iv")
        spread = row.get("spread_pct")
        parts = [f"score={score_txt}", "passing"]
        if delta is not None:
            parts.append(f"Δ={float(delta):.3f}")
        if iv is not None:
            parts.append(f"IV={float(iv):.3f}")
        if spread is not None:
            parts.append(f"spread={float(spread):.2%}")
        return f"- {sym}: " + " ".join(parts)
    kill = row.get("kill_rule") or "filtered"
    return f"- {sym}: score={score_txt} filtered ({kill})"


def build_pool_premarket_context(trade_date: dt.date) -> str:
    """同一批 pool 标的 — Grid / Sonnet 共用输入，互不引用对方输出。"""
    pool_list = pool_symbols()
    pool_syms = pool_symbols_set()
    pool = latest_pool_scan_round()
    scan_time = pool.get("scan_time") or "(missing)"
    age = pool_scan_age_minutes()
    age_txt = f"{age:.0f}m ago" if age is not None else "unknown age"

    passing: dict[str, dict[str, Any]] = {}
    for row in pool.get("universe_scores") or pool.get("candidates") or []:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").upper()
        if sym:
            passing[sym] = {**row, "status": "passing"}

    rej_path = Path(str(pool.get("rejection_log") or ""))
    if not rej_path.is_file():
        rej_dir = BASE_DIR / "logs" / "rejections"
        if rej_dir.is_dir():
            files = sorted(rej_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
            rej_path = files[0] if files else rej_path
    filtered = _pool_rows_from_rejection(rej_path, pool_syms) if rej_path.is_file() else {}

    merged: dict[str, dict[str, Any]] = {}
    for sym in pool_list:
        if sym in passing:
            merged[sym] = passing[sym]
        elif sym in filtered:
            merged[sym] = filtered[sym]

    lines: list[str] = [
        f"Trade date: {trade_date.isoformat()}",
        f"Pool universe ({len(pool_list)}): {', '.join(pool_list)}",
        f"Latest pool quant scan: {scan_time} ({age_txt})",
        "Full pool universe table (today's quant scan — use ALL rows, not just top names):",
    ]
    for sym in pool_list:
        lines.append(_format_score_row(sym, merged.get(sym)))

    digest = pool.get("rejection_digest")
    if digest:
        lines.append("--- rejection digest (pool) ---")
        lines.append(str(digest)[:600])

    if latest_pool_scan_date() != trade_date.isoformat():
        lines.append(
            "WARNING: pool_signals stale for today — CC must not invent fresh scores; "
            "prefer [观察] or wait for rescan."
        )

    lines.append(PREMARKET_FIVE_FIELD_SUFFIX)
    return "\n".join(lines)


def filter_items_to_pool(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed = pool_symbols_set()
    out: list[dict[str, Any]] = []
    for it in items:
        sym = str(it.get("sym") or "").upper()
        if sym and sym in allowed:
            out.append(it)
    return out
