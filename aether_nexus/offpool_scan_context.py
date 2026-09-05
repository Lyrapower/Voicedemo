"""Off-pool scan context for Grid+CC run_scan — stdlib + local modules only."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from offpool_ab_stats import load_offpool_candidates
from pool_config import pool_symbols_set

BASE_DIR = Path(__file__).resolve().parent


def _latest_rejection_log() -> Path | None:
    rej_dir = BASE_DIR / "logs" / "rejections"
    if not rej_dir.is_dir():
        return None
    files = sorted(rej_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _offpool_candidates() -> list[dict[str, Any]]:
    pool_syms = pool_symbols_set()
    rej = _latest_rejection_log()
    if rej is None:
        return []
    return load_offpool_candidates(rej, pool_syms)


def build_offpool_context(trade_date: dt.date) -> str:
    """Whitelist-only prompt for Grid+CC offpool scan."""
    pool_syms = sorted(pool_symbols_set())
    candidates = _offpool_candidates()
    lines: list[str] = [
        f"Trade date: {trade_date.isoformat()}",
        "Off-pool lane — pick ONLY from the candidate whitelist below (report-only).",
        f"Pool exclusion — do NOT duplicate ({len(pool_syms)}): {', '.join(pool_syms) or '(empty)'}",
        "",
        f"Off-pool candidate whitelist ({len(candidates)} symbols, quant-derived):",
    ]
    if candidates:
        for row in candidates:
            lines.append(
                f"- {row['sym']} score={row['score']} killed={row.get('kill_rule') or '?'}"
            )
    else:
        lines.append("- (empty — return {\"items\":[]} )")
    lines.append(
        "\nReturn ONLY valid JSON (no markdown prose):\n"
        '{"items":[{"sym":"TICKER","value":"多·[试探性]","note":"why today + risk","dir":1}]}\n'
        "Rules: up to 3 items; ONLY symbols from the whitelist above; "
        "E-line constitution: single-leg call, long-only — NO bearish/short/neutral-wait tools; "
        "if conviction insufficient return {\"items\":[]}; "
        "dir MUST be 1 for every item; "
        'value must combine direction and confidence [高置信|试探性]; '
        "report-only, no trade instructions; do not fabricate symbols outside the whitelist."
    )
    return "\n".join(lines)
