"""missed_movers gauge — movers top-20 ∖ (heat ∪ watchlist); amber if >3."""
from __future__ import annotations

from typing import Any


def compute_missed_movers(
    gainers: list[dict],
    heat_syms: set[str],
    watch_syms: set[str],
) -> dict[str, Any]:
    covered = {s.upper() for s in heat_syms} | {s.upper() for s in watch_syms}
    missed: list[dict[str, Any]] = []
    for g in (gainers or [])[:20]:
        sym = str(g.get("sym") or g.get("symbol") or "").upper()
        if not sym or sym in covered:
            continue
        missed.append({
            "symbol": sym,
            "ret1d": g.get("ret1d") if g.get("ret1d") is not None else g.get("pct"),
        })
    n = len(missed)
    level = "amber" if n > 3 else "green"
    return {"missed": missed, "count": n, "level": level, "threshold": 3}
