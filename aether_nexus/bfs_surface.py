"""BFS store vs surface filter — keep in sync with alpha-platform/backend/bfs_surface.py."""
from __future__ import annotations

import os
from typing import Any

DEFAULT_SURFACE_DENY = "TSLA,GOOGL,AEHR"


def surface_exclude() -> frozenset[str]:
    return frozenset(
        s.strip().upper()
        for s in os.getenv("SURFACE_DENY", DEFAULT_SURFACE_DENY).split(",")
        if s.strip()
    )


def _sym(row: dict[str, Any]) -> str:
    return str(row.get("sym") or row.get("symbol") or "").upper()


def _has_bid_ask(row: dict[str, Any]) -> bool:
    return row.get("bid") is not None and row.get("ask") is not None


def reconcile_bfs_rows(
    rows: list[dict[str, Any]],
    watchlist: list[str],
    *,
    surface_deny: frozenset[str] | None = None,
) -> dict[str, Any]:
    deny = surface_deny if surface_deny is not None else surface_exclude()
    wl = {str(s).upper() for s in watchlist}
    raw_rows: list[dict[str, Any]] = []
    surface_rows: list[dict[str, Any]] = []
    filtered: list[dict[str, Any]] = []
    excluded: set[str] = set()

    for row in rows:
        sym = _sym(row)
        if not sym:
            continue
        if not _has_bid_ask(row):
            filtered.append({"sym": sym, "reason": "missing bid/ask", "score": row.get("score")})
            continue
        raw_rows.append(row)
        if sym in deny:
            filtered.append({"sym": sym, "reason": "surface_exclude", "score": row.get("score")})
            excluded.add(sym)
        elif sym not in wl:
            filtered.append({"sym": sym, "reason": "not_in_watchlist", "score": row.get("score")})
            excluded.add(sym)
        else:
            surface_rows.append(row)

    surface_filtered = [f for f in filtered if f.get("reason") != "missing bid/ask"]
    return {
        "raw_n": len(raw_rows),
        "surface_n": len(surface_rows),
        "excluded": sorted(excluded),
        "surface_rows": surface_rows,
        "filtered": filtered,
        "surface_filtered": surface_filtered,
        "store_skipped_n": sum(1 for f in filtered if f.get("reason") == "missing bid/ask"),
    }


def format_chain(reconcile: dict[str, Any]) -> str:
    exc = ",".join(reconcile.get("excluded") or []) or "—"
    return (
        f"原始 {reconcile.get('raw_n', 0)} → watchlist 过滤后 "
        f"{reconcile.get('surface_n', 0)}(排除 {exc}) → 详见 aether"
    )
