"""E4-B — dual leaderboard + info_basis tagging."""
from __future__ import annotations

from typing import Any

from pathlib import Path
import datetime as dt

from premarket_ab_clock import AB_LEDGER_START_DATE
from premarket_ab_pairing import (
    VERDICT_WINDOW_DAYS,
    cumulative_paired_returns,
    paired_scorable_dates,
)


def tag_info_basis(item: dict[str, Any]) -> str:
    basis = str(item.get("info_basis") or "").lower()
    if basis in ("snapshot", "world-knowledge", "mixed"):
        return basis
    note = str(item.get("note") or "").lower()
    if "world" in note or "训练" in note:
        return "world-knowledge"
    if item.get("meta", {}).get("route") == "egress":
        return "mixed"
    return "snapshot"


def compute_dual_leaderboard(*, as_of: str | None = None) -> dict[str, Any]:
    dates = paired_scorable_dates(limit=VERDICT_WINDOW_DAYS, for_verdict=True)
    raw_grid, raw_sonnet = cumulative_paired_returns(adjusted=False, for_verdict=True)
    adj_grid, adj_sonnet = cumulative_paired_returns(adjusted=True, for_verdict=True)
    raw_diff = round((raw_sonnet - raw_grid) * 100, 4)
    adj_diff = round((adj_sonnet - adj_grid) * 100, 4)
    info_gap_cost_bps = round((raw_diff - adj_diff) * 100, 2)
    return {
        "ab_ledger_start": AB_LEDGER_START_DATE,
        "verdict_window_days": VERDICT_WINDOW_DAYS,
        "paired_scorable_n": len(dates),
        "raw": {
            "grid_return_30d_pct": raw_grid,
            "sonnet_return_30d_pct": raw_sonnet,
            "diff_pct_pts": raw_diff,
            "answers": "实战谁强",
        },
        "adjusted": {
            "grid_return_30d_pct": adj_grid,
            "sonnet_return_30d_pct": adj_sonnet,
            "diff_pct_pts": adj_diff,
            "answers": "同信息谁强",
            "formula": "剔除 Sonnet独有 ∩ info_basis=world-knowledge ∩ attribution=information 桶后重算",
        },
        "info_gap_cost_bps": info_gap_cost_bps,
        "info_gap_label": "信息差成本(世界知识优势)",
        "info_gap_formula": "info_gap_cost_bps = (raw_Δ − adj_Δ) × 100",
        "consensus_bucket": "both_selected_symbols",
        "info_basis_schema": {
            "field": "info_basis",
            "enum": ["snapshot", "world-knowledge", "mixed"],
            "attribution_field": "attribution",
            "attribution_bucket": "information",
            "since": AB_LEDGER_START_DATE,
        },
    }


def append_transition_log_info_gap(board: dict[str, Any] | None = None) -> None:
    """Monthly info_gap_cost line → TRANSITION_LOG.md (E4-B result metric)."""
    board = board or compute_dual_leaderboard()
    bps = board.get("info_gap_cost_bps")
    if bps is None:
        return
    log_path = Path(__file__).resolve().parent / "docs" / "TRANSITION_LOG.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = (
        f"| {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d')} "
        f"| info_gap_cost | {bps} bps | 信息差成本(世界知识优势) raw−adj | E4-B |"
    )
    if not log_path.is_file():
        log_path.write_text(
            "# TRANSITION_LOG\n\n| date | metric | value | note | lane |\n|---|---|---|---|---|\n",
            encoding="utf-8",
        )
    body = log_path.read_text(encoding="utf-8")
    if line not in body:
        log_path.write_text(body.rstrip() + "\n" + line + "\n", encoding="utf-8")
