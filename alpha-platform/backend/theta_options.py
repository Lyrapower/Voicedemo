"""theta_options.py — Alpha 接 Theta Options VALUE 数据,算 options 因子。

参考 OWS theta_loader.py / engine.py / gex.py,自包含(不依赖 OWS)。

Theta Options VALUE 订阅可用端点:
- /v3/option/history/eod — 期权 EOD 价格(bid/ask/close)
- /v3/option/history/open_interest — OI(独立端点)

Options 因子(日频,17:15 ET 后更新;盘中拉返回最新可用 EOD = 昨日):
- net_gex — Net GEX / Gamma Flip(假设:dealer 净多 call / 净空 put;OI 未归因 = 模型≠数据)
- atm_iv — ATM call/put 的 IV(最接近 spot 的 strike,2% 内取均值)
- total_oi — 总 OI

Env: THETA_BASE(http://host.docker.internal:25503), THETA_STRIKE_DIV(1000),
     ALPHA_THETA_R(0.04), ALPHA_THETA_Q(0.012)
"""
from __future__ import annotations
import os, json, math, urllib.parse, urllib.request, urllib.error, datetime
from typing import Any

DEFAULT_BASE = os.getenv("THETA_BASE", "http://host.docker.internal:25503").rstrip("/")
STRIKE_DIV = float(os.getenv("THETA_STRIKE_DIV", "1000"))
R_DEFAULT = float(os.getenv("ALPHA_THETA_R", "0.04"))
Q_DEFAULT = float(os.getenv("ALPHA_THETA_Q", "0.012"))


def _get(path, params=None, *, base=None):
    b = (base or DEFAULT_BASE).rstrip("/")
    q = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
    url = f"{b}{path}" + (f"?{q}" if q else "")
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} {path}: {e.read().decode('utf-8','replace')[:200]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Theta Terminal 不可达 ({b}): {e.reason}") from e
    if not raw.strip():
        return None
    return json.loads(raw)


def _strike_dollars(raw):
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    if v < 10000:
        return round(v, 4)
    return round(v / STRIKE_DIV, 4)


def _parse_date(d):
    if d is None:
        return None
    if isinstance(d, int):
        s = str(d)
        if len(s) == 8:
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    s = str(d)
    if len(s) >= 10 and s[4] == "-":
        return s[:10]
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


def _norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _bs_price(S, K, T, r, q, sigma, is_call):
    if T <= 0 or sigma <= 0:
        return max(0.0, (S - K) if is_call else (K - S))
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if is_call:
        return S * math.exp(-q * T) * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * math.exp(-q * T) * _norm_cdf(-d1)


def _implied_vol(price, S, K, T, r, q, is_call, lo=0.005, hi=4.0, tol=1e-6):
    if price <= max(0.0, (S - K) if is_call else (K - S)) - 1e-9:
        return None
    plo = _bs_price(S, K, T, r, q, lo, is_call)
    phi_ = _bs_price(S, K, T, r, q, hi, is_call)
    if not (plo - 1e-12 <= price <= phi_ + 1e-12):
        return None
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        pm = _bs_price(S, K, T, r, q, mid, is_call)
        if abs(pm - price) < tol:
            return mid
        if pm < price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _gamma(S, K, T, r, q, sigma, is_call):
    if T <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    return math.exp(-q * T) * _norm_pdf(d1) / (S * sigma * math.sqrt(T))


def _iter_contracts(payload):
    out = []
    if payload is None:
        return out
    if isinstance(payload, dict):
        header = payload.get("header") or {}
        fmt = header.get("format") if isinstance(header, dict) else None
        resp = payload.get("response")
        if resp is None and "contract" in payload:
            resp = [payload]
        if isinstance(resp, list):
            for item in resp:
                if not isinstance(item, dict):
                    continue
                contract = item.get("contract") or {}
                ticks = item.get("ticks") or item.get("data") or []
                if isinstance(ticks, list) and ticks:
                    tick = ticks[-1]
                    if isinstance(tick, dict):
                        row = tick
                    elif isinstance(tick, list):
                        keys = fmt or ["ms_of_day", "open", "high", "low", "close", "volume", "bid", "ask"]
                        row = {keys[i]: tick[i] for i in range(min(len(keys), len(tick)))}
                    else:
                        row = {}
                    out.append((contract, row))
                elif any(k in item for k in ("bid", "ask", "close")):
                    out.append((contract or item, item))
    return out


def _oi_map(payload):
    out = {}
    if not payload or not isinstance(payload, dict):
        return out
    resp = payload.get("response") or []
    if not isinstance(resp, list):
        return out
    for item in resp:
        if not isinstance(item, dict):
            continue
        c = item.get("contract") or {}
        exp_s = _parse_date(c.get("expiration"))
        K = _strike_dollars(c.get("strike"))
        right = str(c.get("right") or "").upper()
        side = "call" if right in ("C", "CALL") else ("put" if right in ("P", "PUT") else "")
        if not exp_s or K is None or not side:
            continue
        data = item.get("data") or []
        oi = 0
        if isinstance(data, list) and data and isinstance(data[-1], dict):
            oi = int(data[-1].get("open_interest") or 0)
        out[(exp_s, K, side)] = oi
    return out


def _build_contracts(root: str, date: str, spot: float, *, base: str | None = None):
    """拉 EOD + OI,构建 contracts 列表 + oi_map。返回 (contracts, oi_map) 或 (None, None)。"""
    ymd = int(date.replace("-", ""))
    asof = datetime.date.fromisoformat(date)
    try:
        bulk = _get("/v3/option/history/eod", {
            "symbol": root, "expiration": "*", "start_date": ymd, "end_date": ymd,
            "date": date, "format": "json",
        }, base=base)
    except RuntimeError:
        try:
            bulk = _get("/v2/bulk_hist/option/eod", {
                "symbol": root, "expiration": "*", "start_date": ymd, "end_date": ymd,
                "date": date, "format": "json",
            }, base=base)
        except RuntimeError:
            return None, None
    pairs = _iter_contracts(bulk)
    if not pairs:
        return None, None
    oi_map = {}
    try:
        oi_payload = _get("/v3/option/history/open_interest", {
            "symbol": root, "expiration": "*", "date": date, "format": "json",
        }, base=base)
        oi_map = _oi_map(oi_payload)
    except RuntimeError:
        pass
    r, q = R_DEFAULT, Q_DEFAULT
    contracts = []
    for contract, row in pairs:
        exp_s = _parse_date(contract.get("expiration") or row.get("expiration"))
        if not exp_s:
            continue
        K = _strike_dollars(contract.get("strike") or row.get("strike"))
        if K is None:
            continue
        right = str(contract.get("right") or row.get("right") or "").upper()
        cp = "call" if right in ("C", "CALL") else ("put" if right in ("P", "PUT") else "")
        if not cp:
            continue
        dte = (datetime.date.fromisoformat(exp_s) - asof).days
        if dte <= 0:
            continue
        T = dte / 365.0
        bid = float(row.get("bid") or 0)
        ask = float(row.get("ask") or 0)
        close = float(row.get("close") or 0)
        price = (bid + ask) / 2 if bid > 0 and ask > 0 else close
        if price <= 0:
            continue
        iv = _implied_vol(price, spot, K, T, r, q, cp == "call")
        if iv is None:
            continue
        oi = oi_map.get((exp_s, K, cp), 0)
        contracts.append({"K": K, "iv": iv, "oi": oi, "cp": cp, "T": T, "exp": exp_s, "dte": dte})
    return contracts, oi_map


def _max_pain(contracts) -> float | None:
    """max_pain = 使 option holder 总赔付最小的 strike(即 holder 最大痛苦位)。"""
    ks = sorted({c["K"] for c in contracts})
    if not ks:
        return None
    best_k, best = None, None
    for k in ks:
        payout = 0.0
        for c in contracts:
            if c["oi"] <= 0:
                continue
            if c["cp"] == "call":
                payout += max(0.0, k - c["K"]) * c["oi"]
            else:
                payout += max(0.0, c["K"] - k) * c["oi"]
        if best is None or payout < best:
            best, best_k = payout, k
    return best_k


def _per_expiry_atm_iv(contracts, spot) -> dict[str, float]:
    """每个 expiration 的 ATM IV(2% 内均值)。返回 {expiry: atm_iv}。"""
    by_exp: dict[str, list[float]] = {}
    for c in contracts:
        if abs(c["K"] - spot) < 0.02 * spot:
            by_exp.setdefault(c["exp"], []).append(c["iv"])
    return {exp: sum(v) / len(v) for exp, v in by_exp.items() if v}


def fetch_option_surface(root: str, date: str, spot: float | None, *, base: str | None = None) -> dict[str, Any] | None:
    """拉 Theta Options VALUE EOD + OI,返回完整期权结构面(断层热力 V1.2 用)。

    比 fetch_option_factors 多暴露:per_strike_gex / per_strike_oi / per_expiry_atm_iv /
    near_next_iv / max_pain。返回 None = 不可达或无数据。
    """
    if spot is None or spot <= 0:
        return None
    contracts, _oi_map = _build_contracts(root, date, spot, base=base)
    if not contracts:
        return None
    r, q = R_DEFAULT, Q_DEFAULT
    per_strike_gex: dict[float, float] = {}
    per_strike_oi: dict[float, dict[str, int]] = {}
    total_oi = 0
    atm_ivs = []
    for c in contracts:
        total_oi += c["oi"]
        g = _gamma(spot, c["K"], c["T"], r, q, c["iv"], c["cp"] == "call")
        contrib = g * c["oi"] * 100 * spot * spot * 0.01 / 1e6
        sign = 1.0 if c["cp"] == "call" else -1.0
        per_strike_gex[c["K"]] = per_strike_gex.get(c["K"], 0.0) + sign * contrib
        slot = per_strike_oi.setdefault(c["K"], {"call": 0, "put": 0})
        slot[c["cp"]] = slot.get(c["cp"], 0) + c["oi"]
        if abs(c["K"] - spot) < 0.02 * spot:
            atm_ivs.append(c["iv"])
    ks = sorted(per_strike_gex)
    total_gex = sum(per_strike_gex.values())
    flip = None
    cum = 0.0
    for a, b in zip(ks, ks[1:]):
        c0, c1 = cum + per_strike_gex[a], cum + per_strike_gex[a] + per_strike_gex[b]
        cum += per_strike_gex[a]
        if (c0 <= 0 <= c1) or (c1 <= 0 <= c0):
            flip = round(a + (b - a) * (0 - c0) / (c1 - c0 + 1e-12), 2)
            break
    atm_iv = sum(atm_ivs) / len(atm_ivs) if atm_ivs else None
    per_exp_iv = _per_expiry_atm_iv(contracts, spot)
    near_next = None
    exp_sorted = sorted(per_exp_iv)
    if len(exp_sorted) >= 2:
        near_next = {"near": per_exp_iv[exp_sorted[0]], "next": per_exp_iv[exp_sorted[1]],
                     "near_exp": exp_sorted[0], "next_exp": exp_sorted[1]}
    return {
        "net_gex": round(total_gex, 2),
        "gamma_flip": flip,
        "atm_iv": round(atm_iv, 4) if atm_iv is not None else None,
        "total_oi": total_oi,
        "n_contracts": len(contracts),
        "oi_available": total_oi > 0,
        "gex_unreliable": total_oi == 0,
        "date": date,
        # V1.2 断层热力新增字段
        "per_strike_gex": {str(k): round(v, 4) for k, v in per_strike_gex.items()},
        "per_strike_oi": {str(k): v for k, v in per_strike_oi.items()},
        "per_expiry_atm_iv": per_exp_iv,
        "near_next_iv": near_next,
        "max_pain": _max_pain(contracts),
    }


def fetch_option_factors(root: str, date: str, spot: float | None, *, base: str | None = None) -> dict[str, Any] | None:
    """拉 Theta Options VALUE EOD + OI,算 {net_gex, atm_iv, total_oi, gamma_flip}。

    返回 None = Theta 不可达或无数据(调用方跳过,不报错)。输出与历史一致(worker 不破)。
    """
    surf = fetch_option_surface(root, date, spot, base=base)
    if surf is None:
        return None
    return {
        "net_gex": surf["net_gex"],
        "gamma_flip": surf["gamma_flip"],
        "atm_iv": surf["atm_iv"],
        "total_oi": surf["total_oi"],
        "n_contracts": surf["n_contracts"],
        "oi_available": surf["oi_available"],
        "gex_unreliable": surf["gex_unreliable"],
        "date": surf["date"],
    }
