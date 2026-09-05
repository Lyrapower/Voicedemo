"""Market-state labels for regime-split IC. Labels at date t use closes ≤ t-1 only."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable

Bar = tuple[str, float, float, float, float, float]  # date, o, h, l, c, v


def _closes(rows: list[Bar]) -> list[tuple[str, float]]:
    return [(r[0], float(r[4])) for r in rows if r[4] is not None and r[4] > 0]


def _sma(xs: list[float], k: int) -> float | None:
    if len(xs) < k:
        return None
    w = xs[-k:]
    return sum(w) / k


def _dates_union(bars: dict[str, list[Bar]]) -> list[str]:
    s: set[str] = set()
    for rows in bars.values():
        for r in rows:
            s.add(r[0])
    return sorted(s)


def _history_through(closes: list[tuple[str, float]], asof: str) -> list[tuple[str, float]]:
    """Closes with date <= asof (inclusive). Caller passes t-1 as asof for label t."""
    return [x for x in closes if x[0] <= asof]


def _prev_date(dates: list[str], t: str) -> str | None:
    prev = None
    for d in dates:
        if d >= t:
            return prev
        prev = d
    return prev


def trend_spy(bars: dict[str, list[Bar]], spy: str = "SPY") -> dict[str, str]:
    """SPY close vs 20dma. Label[t] uses closes ≤ t-1."""
    rows = bars.get(spy) or []
    closes = _closes(rows)
    dates = [d for d, _ in closes]
    out: dict[str, str] = {}
    for i, t in enumerate(dates):
        asof = dates[i - 1] if i else None
        if asof is None:
            continue
        hist = [c for d, c in closes if d <= asof]
        ma = _sma(hist, 20)
        if ma is None or ma == 0:
            continue
        out[t] = "up" if hist[-1] > ma else "down"
    return out


def breadth_sp500(bars: dict[str, list[Bar]], universe: Iterable[str]) -> dict[str, str]:
    """Share of universe with close > own 20dma. Label[t] uses ≤ t-1."""
    univ = [u.upper() for u in universe]
    by_sym = {s: _closes(bars.get(s) or []) for s in univ}
    all_dates = sorted({d for rows in by_sym.values() for d, _ in rows})
    out: dict[str, str] = {}
    for i, t in enumerate(all_dates):
        asof = all_dates[i - 1] if i else None
        if asof is None:
            continue
        above = 0
        n = 0
        for s in univ:
            hist = [c for d, c in by_sym[s] if d <= asof]
            ma = _sma(hist, 20)
            if ma is None:
                continue
            n += 1
            if hist[-1] > ma:
                above += 1
        if n < 480:
            out[t] = "data_short"
            continue
        pct = above / n
        if pct > 0.60:
            out[t] = "wide"
        elif pct < 0.40:
            out[t] = "narrow"
        else:
            out[t] = "mid"
    return out


def _log_std20(closes: list[float]) -> float | None:
    """20 log-return sample std (ddof=1). Need 21 close levels."""
    if len(closes) < 21:
        return None
    w = closes[-21:]
    logs = []
    for j in range(1, 21):
        if w[j - 1] <= 0 or w[j] <= 0:
            return None
        logs.append(math.log(w[j] / w[j - 1]))
    if len(logs) < 20:
        return None
    m = sum(logs) / 20
    var = sum((x - m) ** 2 for x in logs) / 19
    return math.sqrt(var) if var >= 0 else None


def emp_quantile(last: float, window: list[float]) -> float:
    """(#< + 0.5·#=) / n  — R1 midrank percentile."""
    n = len(window)
    if n <= 0:
        return float("nan")
    less = sum(1 for v in window if v < last)
    eq = sum(1 for v in window if v == last)
    return (less + 0.5 * eq) / n


def vol_spy(bars: dict[str, list[Bar]], spy: str = "SPY") -> dict[str, str]:
    """SPY 20d log-vol, 60-obs midrank percentile. Label[t] uses ≤ t-1."""
    closes = _closes(bars.get(spy) or [])
    dates = [d for d, _ in closes]
    vol_series: list[tuple[str, float]] = []
    for i in range(20, len(closes)):
        asof = dates[i]
        v = _log_std20([c for _, c in closes[: i + 1]])
        if v is None:
            continue
        vol_series.append((asof, v))
    out: dict[str, str] = {}
    for i, t in enumerate(dates):
        asof = dates[i - 1] if i else None
        if asof is None:
            continue
        hist = [(d, v) for d, v in vol_series if d <= asof]
        if len(hist) < 60:
            continue
        last = hist[-1][1]
        window = [v for _, v in hist[-60:]]
        q = emp_quantile(last, window)
        if q > 0.70:
            out[t] = "high"
        elif q < 0.30:
            out[t] = "low"
        else:
            out[t] = "mid"
    return out


def width_bucket_from_counts(U: int, M: int, N: int) -> str | None:
    """R1 width interval. Both ends must land in the same bucket or label is missing."""
    if N <= 0:
        return None
    lo = U / N
    hi = (U + M) / N

    def _b(p: float) -> str:
        if p > 0.60:
            return "high"
        if p < 0.40:
            return "low"
        return "mid"

    a, b = _b(lo), _b(hi)
    return a if a == b else None


def width_sp500(
    bars: dict[str, list[Bar]],
    universe: Iterable[str],
    members_on: dict[str, set[str]] | None = None,
) -> dict[str, str]:
    """Width label[t] from t-1 members. Missing window ≠ 'not above'; denom does not shrink."""
    univ = [u.upper() for u in universe]
    by_sym = {s: _closes(bars.get(s) or []) for s in univ}
    if members_on:
        all_dates = sorted(members_on.keys())
    else:
        all_dates = sorted({d for rows in by_sym.values() for d, _ in rows})
    out: dict[str, str] = {}
    for i, t in enumerate(all_dates):
        asof = all_dates[i - 1] if i else None
        if asof is None:
            continue
        members = [s.upper() for s in (members_on[asof] if members_on else univ)]
        N = len(members)
        if N <= 0:
            continue
        U = 0
        M = 0
        for s in members:
            hist = [c for d, c in by_sym.get(s, []) if d <= asof]
            ma = _sma(hist, 20)
            if ma is None:
                M += 1
                continue
            if hist[-1] > ma:
                U += 1
        lab = width_bucket_from_counts(U, M, N)
        if lab:
            out[t] = lab
    return out


def width_diagnostics(
    bars: dict[str, list[Bar]],
    universe: Iterable[str],
    members_on: dict[str, set[str]] | None = None,
) -> dict[str, dict]:
    """Per-t N/U/M and interval for the receipt. Label missing days omitted from labels only."""
    univ = [u.upper() for u in universe]
    by_sym = {s: _closes(bars.get(s) or []) for s in univ}
    if members_on:
        all_dates = sorted(members_on.keys())
    else:
        all_dates = sorted({d for rows in by_sym.values() for d, _ in rows})
    diag: dict[str, dict] = {}
    for i, t in enumerate(all_dates):
        asof = all_dates[i - 1] if i else None
        if asof is None:
            continue
        members = [s.upper() for s in (members_on[asof] if members_on else univ)]
        N = len(members)
        U = 0
        M = 0
        for s in members:
            hist = [c for d, c in by_sym.get(s, []) if d <= asof]
            if _sma(hist, 20) is None:
                M += 1
            elif hist[-1] > _sma(hist, 20):
                U += 1
        lab = width_bucket_from_counts(U, M, N) if N else None
        diag[t] = {
            "N": N, "U": U, "M": M,
            "lo": (U / N) if N else None,
            "hi": ((U + M) / N) if N else None,
            "label": lab,
        }
    return diag


REGIMES = {
    "trend": trend_spy,
    "breadth": breadth_sp500,
    "width": width_sp500,
    "vol": vol_spy,
}


def labels_for(
    kind: str,
    bars: dict[str, list[Bar]],
    universe: Iterable[str] | None = None,
    members_on: dict[str, set[str]] | None = None,
) -> dict[str, str]:
    if kind == "trend":
        return trend_spy(bars)
    if kind == "vol":
        return vol_spy(bars)
    if kind == "width":
        return width_sp500(bars, universe or bars.keys(), members_on=members_on)
    if kind == "breadth":
        return breadth_sp500(bars, universe or bars.keys())
    raise ValueError(f"unknown regime {kind}")


def half_signs_agree(ics: list[tuple[str, float, int]]) -> bool:
    if len(ics) < 2:
        return False
    mid = len(ics) // 2
    a = sum(x[1] for x in ics[:mid]) / mid
    b = sum(x[1] for x in ics[mid:]) / (len(ics) - mid)
    if a == 0 or b == 0:
        return False
    return (a > 0) == (b > 0)


def bucket_verdict(n_obs: int, ic_mean: float | None, ic_t: float | None,
                   ics: list[tuple[str, float, int]], *, min_n: int,
                   full_mean: float | None, bucket: str) -> tuple[str, str]:
    """n≥min_n and half-sample same sign, else insufficient. Gate does not relax with thicker sample."""
    if n_obs < min_n or not half_signs_agree(ics):
        why = f"n_obs={n_obs}<{min_n}" if n_obs < min_n else "half-sample sign flip"
        return "insufficient", why
    if ic_t is None or ic_mean is None:
        return "reject", "no ic"
    if abs(ic_t) > 2:
        if full_mean is not None and full_mean != 0 and (ic_mean > 0) != (full_mean > 0):
            return "regime_flip", f"t={ic_t:.2f} vs full {full_mean:.4f}"
        return f"watch@{bucket}", f"t={ic_t:.2f} ic={ic_mean:.4f}"
    return "reject", f"insig t={ic_t:.2f}"
