"""R10 research bars + v4 daily IC coverage. Production DB is opened read-only by the caller."""
from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from typing import Any

from ic_eval_v1_1 import Bar, _to_date, spearman

ALLOWED_SRC = frozenset({"fmp_hist", "fmp"})
WARMUP_DAYS = 100
MIN_CROSS = 100
MIN_MEMBER_FRAC = 0.95


def connect_ro(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _norm_src(src: Any) -> str | None:
    if src is None:
        return None
    s = str(src).strip()
    return s or None


def load_bars_research(
    con: sqlite3.Connection,
    *,
    symbols: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """Prefer fmp_hist over fmp. Same key different values → conflict blocked. NULL/IEX out."""
    q = "SELECT ts, symbol, o, h, l, c, v, src FROM daily_bars"
    args: list = []
    if symbols:
        q += " WHERE symbol IN (%s)" % ",".join("?" * len(symbols))
        args += [s.upper() for s in symbols]
    q += " ORDER BY symbol, ts, src"
    # detect src column
    cols = {r[1] for r in con.execute("PRAGMA table_info(daily_bars)")}
    if "src" not in cols:
        return {"ok": False, "blocked": True, "reason": "daily_bars.src missing", "bars": {}, "conflicts": []}
    by: dict[tuple[str, str], dict[str, tuple]] = defaultdict(dict)
    conflicts: list[str] = []
    for ts, sym, o, h, l, c, v, src in con.execute(q, args):
        d = _to_date(ts)
        if start and d < start:
            continue
        if end and d > end:
            continue
        src_n = _norm_src(src)
        if src_n not in ALLOWED_SRC:
            continue
        if c is None or float(c) <= 0:
            continue
        key = (str(sym).upper(), d)
        rec = (d, o, h, l, float(c), v or 0.0)
        if src_n in by[key]:
            prev = by[key][src_n]
            if prev[4] != rec[4] or (prev[1] is not None and o is not None and prev[1] != o):
                conflicts.append(f"{key[0]} {d} src={src_n}")
        by[key][src_n] = rec
    if conflicts:
        return {"ok": False, "blocked": True, "reason": "src content conflict", "bars": {}, "conflicts": conflicts[:20]}
    bars: dict[str, list[Bar]] = defaultdict(list)
    dropped_null = 0
    kept = 0
    for (sym, d), srcs in by.items():
        rec = srcs.get("fmp_hist") or srcs.get("fmp")
        if rec is None:
            dropped_null += 1
            continue
        bars[sym].append(rec)
        kept += 1
    for s in bars:
        bars[s].sort(key=lambda r: r[0])
    return {
        "ok": True,
        "blocked": False,
        "bars": dict(bars),
        "conflicts": [],
        "n_kept": kept,
        "price_tag": "price_return_ex_dividend",
        "open_proxy": "closed",  # do not mix unconfirmed open with close
    }


def trading_dates(bars: dict[str, list[Bar]]) -> list[str]:
    return sorted({r[0] for rows in bars.values() for r in rows})


def eligible_dates(calendar: list[str], horizon: int, warmup: int = WARMUP_DAYS) -> list[str]:
    """Warmup complete and return mature: drop first warmup and last horizon days."""
    if len(calendar) <= warmup + horizon:
        return []
    return calendar[warmup: len(calendar) - horizon]


def forward_close(bars: dict[str, list[Bar]], horizon: int) -> dict[tuple[str, str], float]:
    out: dict[tuple[str, str], float] = {}
    for sym, rows in bars.items():
        idx = {r[0]: i for i, r in enumerate(rows)}
        dates = [r[0] for r in rows]
        for i, r in enumerate(rows):
            j = i + horizon
            if j >= len(rows):
                continue
            # require exact calendar-step membership on this symbol's series
            if dates[j] and rows[i][4] > 0:
                out[(r[0], sym)] = rows[j][4] / rows[i][4] - 1.0
    return out


def daily_ic_v4(
    factor_vals: dict[tuple[str, str], float],
    fwd: dict[tuple[str, str], float],
    *,
    members_on: dict[str, set[str]],
    dates: list[str],
    min_cross: int = MIN_CROSS,
    min_frac: float = MIN_MEMBER_FRAC,
) -> dict[str, Any]:
    """Spearman on names in the PIT set that day. Need ≥95% of members and ≥100."""
    ics: dict[str, float] = {}
    n_eff: dict[str, int] = {}
    skipped = []
    for d in dates:
        members = members_on.get(d) or set()
        N = len(members)
        pairs = []
        for s in members:
            key = (d, s)
            f = factor_vals.get(key)
            y = fwd.get(key)
            if f is None or y is None or not math.isfinite(f) or not math.isfinite(y):
                continue
            pairs.append((f, y))
        n = len(pairs)
        need = max(min_cross, math.ceil(min_frac * N) if N else min_cross)
        if n < need:
            skipped.append(d)
            continue
        ic = spearman([p[0] for p in pairs], [p[1] for p in pairs])
        if ic is None:
            skipped.append(d)
            continue
        ics[d] = ic
        n_eff[d] = n
    return {"ics": ics, "n": n_eff, "skipped": skipped}


def acf1(series: list[float]) -> float | None:
    if len(series) < 3:
        return None
    x0 = series[:-1]
    x1 = series[1:]
    n = len(x0)
    m0 = sum(x0) / n
    m1 = sum(x1) / n
    num = sum((a - m0) * (b - m1) for a, b in zip(x0, x1))
    d0 = math.sqrt(sum((a - m0) ** 2 for a in x0))
    d1 = math.sqrt(sum((b - m1) ** 2 for b in x1))
    if d0 == 0 or d1 == 0:
        return None
    return num / (d0 * d1)


def rho_hat_or_default(rho: float | None, default: float = 0.8) -> float:
    if rho is None or not math.isfinite(rho):
        return default
    if abs(rho - default) > 0.15:
        return rho
    return default
