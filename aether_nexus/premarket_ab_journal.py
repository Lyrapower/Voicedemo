"""Premarket A/B journals — physical separation, never merge stats."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Literal

Chain = Literal["grid", "sonnet"]

BASE_DIR = Path(__file__).resolve().parent
JOURNAL_DIR = BASE_DIR / "traces" / "premarket_ab"
JOURNAL_GRID = JOURNAL_DIR / "journal_grid.jsonl"
JOURNAL_SONNET = JOURNAL_DIR / "journal_sonnet.jsonl"
STATS_GRID = JOURNAL_DIR / "stats_grid.json"
STATS_SONNET = JOURNAL_DIR / "stats_sonnet.json"


def _load_stats(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_stats(path: Path, all_stats: dict[str, Any]) -> None:
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(all_stats, ensure_ascii=False, indent=2), encoding="utf-8")


def is_context_asymmetric(trade_date: str) -> bool:
    """True when A/B context was asymmetric — day voided from rolling ledger."""
    for path in (STATS_GRID, STATS_SONNET):
        entry = _load_stats(path).get(trade_date)
        if isinstance(entry, dict) and entry.get("context_asymmetric"):
            return True
    return False


def mark_context_asymmetric(trade_date: str, *, reason: str) -> dict[str, Any]:
    """Flag a trade date void on both chain ledgers — preserves existing stats."""
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    out: dict[str, Any] = {}
    for chain in ("grid", "sonnet"):
        path = _stats_path(chain)
        all_stats = _load_stats(path)
        entry = dict(all_stats.get(trade_date) or {"chain": chain, "date": trade_date})
        entry["context_asymmetric"] = True
        entry["context_asymmetric_reason"] = reason
        entry["ab_void"] = True
        entry["verdict"] = "void"
        entry["context_degraded"] = True
        entry["information_asymmetry"] = "declared"
        entry["updated_at"] = ts
        all_stats[trade_date] = entry
        _write_stats(path, all_stats)
        out[chain] = entry
    return out


def void_premarket_range(
    start_date: str,
    end_date: str,
    *,
    reason: str = "pipeline_stall",
) -> list[dict[str, Any]]:
    """Void inclusive date range on both A/B ledgers (30d rolling excludes ab_void)."""
    start = dt.date.fromisoformat(start_date)
    end = dt.date.fromisoformat(end_date)
    out: list[dict[str, Any]] = []
    d = start
    while d <= end:
        out.append(mark_context_asymmetric(d.isoformat(), reason=reason))
        d += dt.timedelta(days=1)
    return out


def _journal_path(chain: Chain) -> Path:
    return JOURNAL_GRID if chain == "grid" else JOURNAL_SONNET


def _stats_path(chain: Chain) -> Path:
    return STATS_GRID if chain == "grid" else STATS_SONNET


def append_premarket_journal(
    *,
    chain: Chain,
    trade_date: str,
    items: list[dict[str, Any]],
    meta: dict[str, Any] | None = None,
) -> None:
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    path = _journal_path(chain)
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as f:
        for it in items:
            try:
                from premarket_ab_scoring import tag_info_basis

                basis = tag_info_basis(it)
            except Exception:
                basis = "snapshot"
            row = {
                "ts": ts,
                "date": trade_date,
                "chain": chain,
                "sym": it.get("sym"),
                "dir": it.get("dir"),
                "confidence": it.get("confidence"),
                "value": it.get("value"),
                "note": it.get("note"),
                "info_basis": basis,
                "attribution": it.get("attribution") or (meta or {}).get("attribution"),
                "meta": meta or {},
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def reconcile_chain(chain: Chain, trade_date: str, *, outcomes: dict[str, float] | None = None) -> dict[str, Any]:
    """盘后对账 — 各链独立统计，永不合并。"""
    path = _journal_path(chain)
    if not path.is_file():
        return {"chain": chain, "date": trade_date, "n_items": 0}
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("date") == trade_date:
            rows.append(row)
    outcomes = outcomes or {}
    wins = losses = flat = data_missing = 0
    signed_rets: list[float] = []
    for row in rows:
        sym = str(row.get("sym") or "").upper()
        d = int(row.get("dir") or 0)
        ret = outcomes.get(sym)
        if d == 0:
            # legitimate observe / skip
            flat += 1
            continue
        if ret is None:
            # M1: directional signal but no return data — distinct from a deliberate skip.
            # Previously lumped into `flat`, hiding broken-data days as "no signal".
            data_missing += 1
            continue
        signed_rets.append(ret * d)
        if (d > 0 and ret > 0) or (d < 0 and ret < 0):
            wins += 1
        else:
            losses += 1
    summary = {
        "chain": chain,
        "date": trade_date,
        "n_items": len(rows),
        "wins": wins,
        "losses": losses,
        "flat": flat,
        "data_missing": data_missing,
        "win_rate": round(wins / max(wins + losses, 1), 4),
        "return_pct": round(sum(signed_rets) / len(signed_rets), 6) if signed_rets else None,
        "n_scored": len(signed_rets),
        "outcomes": {k: round(v, 6) for k, v in outcomes.items()} if outcomes else {},
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    if chain == "sonnet" and outcomes:
        from premarket_ab_pairing import daily_returns_for_date

        _, adj_ret = daily_returns_for_date(trade_date, outcomes, adjusted=True)
        summary["adjusted_return_pct"] = adj_ret
    elif chain == "grid":
        summary["adjusted_return_pct"] = summary["return_pct"]
    stats_path = _stats_path(chain)
    all_stats = _load_stats(stats_path)
    prior = all_stats.get(trade_date) if isinstance(all_stats.get(trade_date), dict) else {}
    from premarket_ab_clock import ab_ledger_meta

    clock = ab_ledger_meta(trade_date, void=bool(prior.get("context_asymmetric")))
    if clock["warmup"]:
        summary["warmup"] = True
        summary["ab_void"] = True
        summary["verdict"] = "warmup"
        summary["context_asymmetric_reason"] = prior.get("context_asymmetric_reason") or "architecture_cutover_0714"
    if prior.get("context_asymmetric"):
        summary["context_asymmetric"] = True
        summary["context_asymmetric_reason"] = prior.get("context_asymmetric_reason")
        summary["ab_void"] = True
    all_stats[trade_date] = summary
    _write_stats(stats_path, all_stats)
    return summary
