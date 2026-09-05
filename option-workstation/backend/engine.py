"""engine.py —— Option Workstation 确定性定价引擎(纯标准库,零依赖)
守恒手写 v1。宪法:所有数字出自此处,LLM 零参与。
覆盖:BS 欧式、CRR 二叉树美式(离散股息简化为连续折算)、
隐含波动率(二分)、Greeks(数值)、二次微笑拟合(v1,SVI 升级路留)、RMSE。
"""
from __future__ import annotations
import math

SQRT_2PI = math.sqrt(2.0 * math.pi)


def _phi(x): return math.exp(-0.5 * x * x) / SQRT_2PI


def _N(x): return 0.5 * math.erfc(-x / math.sqrt(2.0))


def bs_price(S, K, T, r, q, sigma, is_call):
    if T <= 0 or sigma <= 0:
        intrinsic = max(0.0, (S - K) if is_call else (K - S))
        return intrinsic
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if is_call:
        return S * math.exp(-q * T) * _N(d1) - K * math.exp(-r * T) * _N(d2)
    return K * math.exp(-r * T) * _N(-d2) - S * math.exp(-q * T) * _N(-d1)


def crr_american(S, K, T, r, q, sigma, is_call, steps=120):
    """CRR 二叉树美式。股息以连续收益率 q 计(v1 简化,离散股息升级路留)。"""
    if T <= 0 or sigma <= 0:
        return max(0.0, (S - K) if is_call else (K - S))
    dt = T / steps
    u = math.exp(sigma * math.sqrt(dt)); d = 1.0 / u
    disc = math.exp(-r * dt)
    p = (math.exp((r - q) * dt) - d) / (u - d)
    p = min(max(p, 0.0), 1.0)
    prices = [S * (u ** j) * (d ** (steps - j)) for j in range(steps + 1)]
    vals = [max(0.0, (x - K) if is_call else (K - x)) for x in prices]
    for i in range(steps - 1, -1, -1):
        for j in range(i + 1):
            spot = S * (u ** j) * (d ** (i - j))
            cont = disc * (p * vals[j + 1] + (1 - p) * vals[j])
            exer = max(0.0, (spot - K) if is_call else (K - spot))
            vals[j] = max(cont, exer)
    return vals[0]


def implied_vol(price, S, K, T, r, q, is_call, american=False, lo=0.005, hi=4.0, tol=1e-6):
    """二分求 IV。价格低于内在价值或不可解 → None(数据层责任,不硬编)。"""
    f = crr_american if american else bs_price
    if price <= max(0.0, (S - K) if is_call else (K - S)) - 1e-9:
        return None
    plo = f(S, K, T, r, q, lo, is_call); phi_ = f(S, K, T, r, q, hi, is_call)
    if not (plo - 1e-12 <= price <= phi_ + 1e-12):
        return None
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        pm = f(S, K, T, r, q, mid, is_call)
        if abs(pm - price) < tol:
            return mid
        if pm < price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def greeks(S, K, T, r, q, sigma, is_call, american=False):
    """数值 Greeks(中心差分)。delta/gamma/vega/theta(每日)。"""
    f = (lambda s, v, t: crr_american(s, K, t, r, q, v, is_call)) if american \
        else (lambda s, v, t: bs_price(s, K, t, r, q, v, is_call))
    dS = S * 1e-3; dV = 1e-4; dT = min(1.0 / 365.0, T * 0.5) if T > 0 else 0
    p0 = f(S, sigma, T)
    delta = (f(S + dS, sigma, T) - f(S - dS, sigma, T)) / (2 * dS)
    gamma = (f(S + dS, sigma, T) - 2 * p0 + f(S - dS, sigma, T)) / (dS * dS)
    vega = (f(S, sigma + dV, T) - f(S, sigma - dV, T)) / (2 * dV) / 100.0
    theta = ((f(S, sigma, T - dT) - p0) / dT / 365.0) if T > dT else 0.0
    return {"price": p0, "delta": delta, "gamma": gamma, "vega": vega, "theta": theta}


def fit_smile(points):
    """二次微笑拟合(v1):w=iv,对 m=ln(K/S) 拟合 iv = a + b·m + c·m²(正名:全链 spot 口径,非 forward)。
    纯正规方程 3x3;返回 (a,b,c,rmse)。SVI 无套利拟合为升级路,已标注。"""
    n = len(points)
    if n < 3:
        return None
    Sx = [0.0] * 5; Sy = [0.0] * 3
    for m, iv in points:
        mm = [1.0, m, m * m, m ** 3, m ** 4]
        for k in range(5):
            Sx[k] += mm[k]
        Sy[0] += iv; Sy[1] += iv * m; Sy[2] += iv * m * m
    A = [[Sx[0], Sx[1], Sx[2]], [Sx[1], Sx[2], Sx[3]], [Sx[2], Sx[3], Sx[4]]]
    b = Sy[:]
    # 高斯消元
    for i in range(3):
        piv = max(range(i, 3), key=lambda r_: abs(A[r_][i]))
        if abs(A[piv][i]) < 1e-12:
            return None
        A[i], A[piv] = A[piv], A[i]; b[i], b[piv] = b[piv], b[i]
        for r_ in range(i + 1, 3):
            fct = A[r_][i] / A[i][i]
            for c_ in range(i, 3):
                A[r_][c_] -= fct * A[i][c_]
            b[r_] -= fct * b[i]
    x = [0.0] * 3
    for i in range(2, -1, -1):
        x[i] = (b[i] - sum(A[i][j] * x[j] for j in range(i + 1, 3))) / A[i][i]
    a, bb, c = x
    sse = sum((a + bb * m + c * m * m - iv) ** 2 for m, iv in points)
    rmse = math.sqrt(sse / n)
    return {"a": a, "b": bb, "c": c, "rmse": rmse}


def pop_lognormal(S, T, sigma, payoff_fn, n=241, width=4.0):
    """到期获利概率:S_T 对数正态(ATM IV,漂移 0,研究口径已标注),
    数值积分 payoff>0 的概率质量。"""
    if T <= 0 or sigma <= 0:
        return 1.0 if payoff_fn(S) > 0 else 0.0
    mu = math.log(S) - 0.5 * sigma * sigma * T
    sd = sigma * math.sqrt(T)
    lo, hi = mu - width * sd, mu + width * sd
    step = (hi - lo) / (n - 1)
    prob = 0.0
    for i in range(n):
        x = lo + i * step
        w = step * _phi((x - mu) / sd) / sd
        if payoff_fn(math.exp(x)) > 0:
            prob += w
    return min(1.0, prob)
