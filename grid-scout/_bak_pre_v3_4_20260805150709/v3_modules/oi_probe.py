"""模块① · OI 异动探针(Polygon Options Starter)。
确定性规则:OI 增量 top10 + Vol/OI>3 标星。
缺 POLYGON_API_KEY → ok=False,不编数字。
"""
from __future__ import annotations
import os
from .http_util import http_get_json

POLYGON_KEY = os.getenv("POLYGON_API_KEY", "").strip()
UNDERLYINGS = ("SPY", "QQQ", "NVDA")


def _snapshot(ul: str) -> list[dict]:
    url = (
        "https://api.polygon.io/v3/snapshot/options/%s?limit=250&apiKey=%s"
        % (ul, POLYGON_KEY)
    )
    data = http_get_json(url, timeout=40)
    return list(data.get("results") or [])


def _row(ul: str, r: dict) -> dict | None:
    det = r.get("details") or {}
    day = r.get("day") or {}
    greeks = r.get("greeks") or {}
    strike = det.get("strike_price")
    cp = (det.get("contract_type") or "").lower()
    if cp in ("call", "c"):
        cp_s = "C"
    elif cp in ("put", "p"):
        cp_s = "P"
    else:
        return None
    oi = r.get("open_interest")
    if oi is None:
        oi = day.get("open_interest")
    vol = day.get("volume") or 0
    # Polygon snapshot 常无昨日 OI;用 day.change / 或缺则用 volume 作代理并标注
    oi_chg = day.get("change")  # not always OI change
    prev_oi = r.get("prev_open_interest") or day.get("previous_open_interest")
    if prev_oi is not None and oi is not None:
        try:
            oi_delta = int(oi) - int(prev_oi)
        except Exception:
            oi_delta = None
    else:
        oi_delta = None
    try:
        voi = (float(vol) / float(oi)) if oi and float(oi) > 0 else None
    except Exception:
        voi = None
    try:
        k = float(strike)
        k_s = str(int(k)) if k == int(k) else str(k)
    except Exception:
        k_s = str(strike)
    return {
        "ul": ul,
        "label": "%s %s%s" % (ul, k_s, cp_s),
        "strike": strike,
        "cp": cp_s,
        "oi": oi,
        "oi_delta": oi_delta,
        "volume": vol,
        "vol_oi": round(voi, 2) if voi is not None else None,
        "expiry": det.get("expiration_date"),
        "star": bool(voi is not None and voi > 3),
    }


def fetch_oi_probe() -> dict:
    if not POLYGON_KEY:
        return {
            "ok": False,
            "error": "POLYGON_API_KEY 未设置——模块① BLOCKED(Options Starter key)",
            "rows": [],
            "stars": [],
            "rule": "OI增量 top10 + Vol/OI>3 标星",
        }
    rows, stars, errs = [], [], []
    for ul in UNDERLYINGS:
        try:
            for r in _snapshot(ul):
                row = _row(ul, r)
                if row:
                    rows.append(row)
                    if row["star"]:
                        stars.append(row)
        except Exception as e:
            errs.append("%s:%s" % (ul, str(e)[:120]))
    # 有 oi_delta 用增量榜;否则用 volume 榜并标注口径
    with_delta = [r for r in rows if r.get("oi_delta") is not None]
    if with_delta:
        ranked = sorted(with_delta, key=lambda x: abs(x["oi_delta"] or 0), reverse=True)[:10]
        metric = "oi_delta"
    else:
        ranked = sorted(rows, key=lambda x: x.get("volume") or 0, reverse=True)[:10]
        metric = "volume_proxy(无昨日OI字段)"
    star_ranked = sorted(stars, key=lambda x: x.get("vol_oi") or 0, reverse=True)[:10]
    return {
        "ok": bool(ranked) and not (errs and not ranked),
        "error": "; ".join(errs) if errs else "",
        "rows": ranked,
        "stars": star_ranked,
        "metric": metric,
        "rule": "OI增量 top10 + Vol/OI>3 标星",
    }
