"""v4 joint calendar-grid HAC + Holm. No ridge, no pinv, no unpublished small-sample fixes."""
from __future__ import annotations

import math
from typing import Any

# bucket order is registered (R3 / 估计器约定)
TREND_BUCKETS = ("down", "up")
THREE_BUCKETS = ("low", "mid", "high")
TREND_C = [[-1.0, 1.0]]
THREE_C = [[-1.0, 1.0, 0.0], [-1.0, 0.0, 1.0]]
HYPOTHESIS_IDS = (
    "mom_5.trend", "mom_5.width", "mom_5.vol",
    "mom_20.trend", "mom_20.width", "mom_20.vol",
    "rev_1.trend", "rev_1.width", "rev_1.vol",
    "vol_20.trend", "vol_20.width", "vol_20.vol",
)
M_HOLM = 12


def bandwidths(T: int, h: int) -> tuple[int, int]:
    l1 = max(h - 1, math.ceil(T ** (1.0 / 3.0)))
    l2 = max(2 * l1, 20)
    return l1, l2


def _eye(n: int) -> list[list[float]]:
    return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]


def mat_mul(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    n, m, p = len(A), len(A[0]), len(B[0])
    out = [[0.0] * p for _ in range(n)]
    for i in range(n):
        for k in range(m):
            aik = A[i][k]
            if aik == 0:
                continue
            for j in range(p):
                out[i][j] += aik * B[k][j]
    return out


def mat_vec(A: list[list[float]], v: list[float]) -> list[float]:
    return [sum(A[i][j] * v[j] for j in range(len(v))) for i in range(len(A))]


def invert(A: list[list[float]], *, tol: float = 1e-12) -> list[list[float]] | None:
    n = len(A)
    M = [A[i][:] + _eye(n)[i] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < tol:
            return None
        if piv != col:
            M[col], M[piv] = M[piv], M[col]
        div = M[col][col]
        for j in range(2 * n):
            M[col][j] /= div
        for r in range(n):
            if r == col:
                continue
            f = M[r][col]
            if f == 0:
                continue
            for j in range(2 * n):
                M[r][j] -= f * M[col][j]
    return [row[n:] for row in M]


def cholesky_psd(A: list[list[float]], *, eps: float = 1e-9) -> bool:
    n = len(A)
    L = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = A[i][j] - sum(L[i][k] * L[j][k] for k in range(j))
            if i == j:
                if s < -eps:
                    return False
                L[i][j] = math.sqrt(max(s, 0.0))
            else:
                if L[j][j] <= eps:
                    if abs(s) <= eps:
                        L[i][j] = 0.0
                    else:
                        return False
                else:
                    L[i][j] = s / L[j][j]
    return True


def finite_mat(A: list[list[float]]) -> bool:
    return all(math.isfinite(x) for row in A for x in row)


def chi2_sf(w: float, df: int) -> float:
    if not math.isfinite(w) or w < 0 or df <= 0:
        return float("nan")
    if df == 1:
        return math.erfc(math.sqrt(w / 2.0))
    if df == 2:
        return math.exp(-w / 2.0)
    # df>2 not used; keep a simple series fallback
    # regularized gamma Q(df/2, w/2) — only df=1,2 registered
    return float("nan")


def one_hot(label: str | None, buckets: tuple[str, ...]) -> list[float]:
    x = [0.0] * len(buckets)
    if label in buckets:
        x[buckets.index(label)] = 1.0
    return x


def design(
    dates: list[str],
    y: dict[str, float],
    labels: dict[str, str],
    buckets: tuple[str, ...],
) -> dict[str, Any]:
    """m_t / x_t on the full calendar grid. Invalid day: m=0, x=0, y unused."""
    T = len(dates)
    m = []
    X = []
    yy = []
    for d in dates:
        lab = labels.get(d)
        has_y = d in y and y[d] is not None and math.isfinite(y[d])
        ok = bool(lab in buckets and has_y)
        m.append(1.0 if ok else 0.0)
        X.append(one_hot(lab if ok else None, buckets))
        yy.append(float(y[d]) if ok else 0.0)
    return {"T": T, "m": m, "X": X, "y": yy, "dates": dates, "buckets": buckets}


def estimate(grid: dict[str, Any], L: int) -> dict[str, Any]:
    """A, b, S_L, V_L. Invalid days contribute u=0 (never 0*NaN)."""
    T = grid["T"]
    K = len(grid["buckets"])
    m, X, y = grid["m"], grid["X"], grid["y"]
    if L >= T:
        return {"ok": False, "reason": "L>=T"}
    A = [[0.0] * K for _ in range(K)]
    xy = [0.0] * K
    for t in range(T):
        if m[t] == 0:
            continue
        xt, yt = X[t], y[t]
        for i in range(K):
            xy[i] += xt[i] * yt
            for j in range(K):
                A[i][j] += xt[i] * xt[j]
    Ainv = invert(A)
    if Ainv is None:
        return {"ok": False, "reason": "A_singular", "A": A}
    b = mat_vec(Ainv, xy)
    u = []
    for t in range(T):
        if m[t] == 0:
            u.append([0.0] * K)
            continue
        fitted = sum(X[t][k] * b[k] for k in range(K))
        resid = y[t] - fitted
        u.append([X[t][k] * resid for k in range(K)])
    S = [[0.0] * K for _ in range(K)]
    for t in range(T):
        for i in range(K):
            for j in range(K):
                S[i][j] += u[t][i] * u[t][j]
    for ell in range(1, L + 1):
        w = 1.0 - ell / (L + 1.0)
        G = [[0.0] * K for _ in range(K)]
        for t in range(ell, T):
            for i in range(K):
                for j in range(K):
                    G[i][j] += u[t][i] * u[t - ell][j]
        for i in range(K):
            for j in range(K):
                S[i][j] += w * (G[i][j] + G[j][i])
    if not finite_mat(S):
        return {"ok": False, "reason": "S_not_finite", "A": A, "b": b}
    V = mat_mul(mat_mul(Ainv, S), Ainv)
    if not finite_mat(V):
        return {"ok": False, "reason": "V_not_finite", "A": A, "b": b, "S": S}
    if not cholesky_psd(V):
        return {"ok": False, "reason": "V_not_psd", "A": A, "b": b, "S": S, "V": V}
    return {"ok": True, "A": A, "Ainv": Ainv, "b": b, "S": S, "V": V, "u": u, "L": L}


def wald(b: list[float], V: list[list[float]], C: list[list[float]]) -> dict[str, Any]:
    CV = mat_mul(C, V)
    CVC = mat_mul(CV, [[C[j][i] for j in range(len(C))] for i in range(len(C[0]))])
    # C is r x K; C V C' is r x r
    Ct = [[C[j][i] for j in range(len(C))] for i in range(len(C[0]))]
    CVC = mat_mul(mat_mul(C, V), Ct)
    if not finite_mat(CVC):
        return {"ok": False, "reason": "CVC_not_finite"}
    CVCinv = invert(CVC)
    if CVCinv is None:
        return {"ok": False, "reason": "CVC_singular"}
    Cb = mat_vec(C, b)
    # W = (Cb)' (CVC)^{-1} (Cb)
    tmp = mat_vec(CVCinv, Cb)
    W = sum(Cb[i] * tmp[i] for i in range(len(Cb)))
    df = len(C)
    p = chi2_sf(W, df)
    if not math.isfinite(W) or not math.isfinite(p):
        return {"ok": False, "reason": "W_or_p_not_finite", "W": W, "df": df}
    return {"ok": True, "W": W, "p": p, "df": df, "Cb": Cb}


def joint_test(
    dates: list[str],
    y: dict[str, float],
    labels: dict[str, str],
    kind: str,
    h: int,
) -> dict[str, Any]:
    buckets = TREND_BUCKETS if kind == "trend" else THREE_BUCKETS
    C = TREND_C if kind == "trend" else THREE_C
    grid = design(dates, y, labels, buckets)
    T = grid["T"]
    L1, L2 = bandwidths(T, h)
    e1 = estimate(grid, L1)
    e2 = estimate(grid, L2)
    if not e1.get("ok") or not e2.get("ok"):
        return {
            "ok": False,
            "reason": "bandwidth_invalid",
            "why1": e1.get("reason"),
            "why2": e2.get("reason"),
            "L1": L1, "L2": L2, "T": T,
            "grid": grid,
        }
    w1 = wald(e1["b"], e1["V"], C)
    w2 = wald(e2["b"], e2["V"], C)
    if not w1.get("ok") or not w2.get("ok"):
        return {
            "ok": False,
            "reason": "wald_invalid",
            "why1": w1.get("reason"),
            "why2": w2.get("reason"),
            "L1": L1, "L2": L2, "T": T,
            "e1": e1, "e2": e2,
        }
    p_robust = max(w1["p"], w2["p"])
    return {
        "ok": True,
        "T": T, "L1": L1, "L2": L2,
        "buckets": buckets,
        "b": e2["b"],
        "V": e2["V"],
        "e1": e1, "e2": e2,
        "W_L1": w1["W"], "p_L1": w1["p"],
        "W_L2": w2["W"], "p_L2": w2["p"],
        "p_robust": p_robust,
        "grid": grid,
        "desc_ci": desc_ci(e2["b"], e2["V"]),
    }


def desc_ci(b: list[float], V: list[list[float]]) -> list[tuple[float, float] | None]:
    out: list[tuple[float, float] | None] = []
    for k, bk in enumerate(b):
        vkk = V[k][k]
        if vkk < 0 or not math.isfinite(vkk):
            out.append(None)
            continue
        se = math.sqrt(vkk)
        out.append((bk - 1.96 * se, bk + 1.96 * se))
    return out


def holm(p_by_id: dict[str, float | None]) -> dict[str, dict[str, Any]]:
    """Fixed m=12. Invalid items occupy p=1; raw p stays empty."""
    items = []
    for hid in HYPOTHESIS_IDS:
        raw = p_by_id.get(hid)
        if raw is None or not math.isfinite(raw):
            items.append((hid, 1.0, None))
        else:
            items.append((hid, float(raw), float(raw)))
    ordered = sorted(items, key=lambda z: z[1])
    adj_run = 0.0
    mapped: dict[str, float] = {}
    for i, (hid, p_use, raw) in enumerate(ordered, start=1):
        cand = (M_HOLM - i + 1) * p_use
        adj_run = max(adj_run, cand)
        mapped[hid] = min(1.0, adj_run)
    out = {}
    for hid, p_use, raw in items:
        out[hid] = {"p_raw": raw, "p_holm": mapped[hid], "placeholder": raw is None}
    return out


def segments(dates: list[str], labels: dict[str, str], bucket: str) -> list[tuple[str, str, int]]:
    """Unknown label breaks a segment. IC-missing days do not (caller passes label dates)."""
    segs: list[tuple[str, str, int]] = []
    cur_start = None
    cur_n = 0
    prev = None
    for d in dates:
        lab = labels.get(d)
        if lab == bucket:
            if cur_start is None:
                cur_start = d
                cur_n = 1
            else:
                cur_n += 1
            prev = d
        else:
            if cur_start is not None and prev is not None:
                segs.append((cur_start, prev, cur_n))
            cur_start = None
            cur_n = 0
            prev = None
    if cur_start is not None and prev is not None:
        segs.append((cur_start, prev, cur_n))
    return segs


def longest_segment(segs: list[tuple[str, str, int]]) -> tuple[str, str, int] | None:
    if not segs:
        return None
    # longest by day count; tie → earliest start
    return sorted(segs, key=lambda s: (-s[2], s[0]))[0]


def drop_longest_labels(labels: dict[str, str], dates: list[str], bucket: str) -> dict[str, str]:
    segs = segments(dates, labels, bucket)
    drop = longest_segment(segs)
    if drop is None:
        return dict(labels)
    a, b, _ = drop
    out = dict(labels)
    for d in dates:
        if a <= d <= b and out.get(d) == bucket:
            out.pop(d, None)
    return out


def coverage_ok(
    *,
    eligible_days: list[str],
    ic_dates: set[str],
    labels: dict[str, str],
    buckets: tuple[str, ...],
    L2: int,
) -> dict[str, Any]:
    """R5. Unknown-label days stay in the denominator."""
    denom = len(eligible_days)
    numer = sum(1 for d in eligible_days if d in ic_dates and labels.get(d) in buckets)
    full_rate = (numer / denom) if denom else 0.0
    per: dict[str, Any] = {}
    ok = full_rate >= 0.95
    for b in buckets:
        lab_days = [d for d in eligible_days if labels.get(d) == b]
        ic_b = [d for d in lab_days if d in ic_dates]
        segs = segments(eligible_days, labels, b)
        segs_eff = [s for s in segs if any(d in ic_dates and a <= d <= c for d in eligible_days for a, c, _ in [s])]
        # segment effective = at least one valid IC day in the segment
        segs_eff = []
        for a, c, n in segs:
            if any(a <= d <= c and d in ic_dates for d in eligible_days):
                segs_eff.append((a, c, n))
        rate = (len(ic_b) / len(lab_days)) if lab_days else 0.0
        n_eff = len(ic_b)
        need_days = 2 * (L2 + 1)
        bucket_ok = n_eff >= 60 and len(segs_eff) >= 3 and n_eff >= need_days and rate >= 0.95
        per[b] = {
            "n_label": len(lab_days),
            "n_ic": n_eff,
            "rate": rate,
            "n_seg": len(segs),
            "n_seg_eff": len(segs_eff),
            "need_days": need_days,
            "ok": bucket_ok,
        }
        if lab_days and not bucket_ok:
            ok = False
    if full_rate < 0.95:
        ok = False
    return {"ok": ok, "full_rate": full_rate, "numer": numer, "denom": denom, "buckets": per}


def verdict(blocked: bool, insuff: bool, p_holm: float | None) -> str:
    if blocked:
        return "blocked"
    if insuff:
        return "insufficient"
    if p_holm is not None and p_holm <= 0.05:
        return "regime_diff"
    return "no_detected_difference"
