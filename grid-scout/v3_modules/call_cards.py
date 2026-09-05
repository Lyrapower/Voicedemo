"""模块③ · 单腿 Call 候选卡。
筛:IVR<25 & 价差<4% & OI>1万 & 昨 OI 增幅 top10(有 Polygon 时)。
无 Polygon 时:仅用 workstation 链做结构演示,强制标注 source,且 OI 门槛如实失败。
"""
from __future__ import annotations
import datetime as dt
import os
from .http_util import http_get_json
from .workstation import fetch_workstation

POLYGON_KEY = os.getenv("POLYGON_API_KEY", "").strip()
IVR_MAX = 25.0
SPREAD_MAX_PCT = 4.0
OI_MIN = 10_000


def _expiry_label(expiry: str | None, dte: int | None) -> str:
    if expiry:
        try:
            d = dt.date.fromisoformat(str(expiry)[:10])
            return d.strftime("%m/%d")
        except Exception:
            return str(expiry)[:10]
    if dte is not None:
        return "DTE%s" % dte
    return "?"


def _seven_lights(spread_pct, ivr, oi, mid) -> str:
    lamps = []
    lamps.append("绿" if spread_pct is not None and spread_pct < SPREAD_MAX_PCT else "红")
    lamps.append("绿" if ivr is not None and ivr < IVR_MAX else "红")
    lamps.append("绿" if oi is not None and oi >= OI_MIN else "红")
    lamps.append("绿" if mid is not None and mid > 0 else "红")
    # 简化七问灯:流动性/IVR/OI/报价 四项可见;其余标灰
    return "价差%s·IVR%s·OI%s·报价%s·其余灰(无实时七问API)" % tuple(lamps)


def cards_from_ows(ws_items: dict) -> dict:
    chain = ws_items.get("chain") or []
    spot = ws_items.get("spot")
    ivr = ws_items.get("ivr")
    src = ws_items.get("source") or "ows"
    date = ws_items.get("date")
    ul = ws_items.get("underlying") or "SPY"
    cands = []
    near = []
    for r in chain:
        if (r.get("cp") or "").lower() not in ("call", "c"):
            continue
        bid, ask, mid = r.get("bid"), r.get("ask"), r.get("mid")
        oi = r.get("oi") or 0
        try:
            spread_pct = 100.0 * (float(ask) - float(bid)) / float(mid) if mid else None
        except Exception:
            spread_pct = None
        K = r.get("K")
        dte = r.get("dte")
        row = {
            "ul": ul,
            "expiry": _expiry_label(None, dte),
            "K": K,
            "cp": "C",
            "mid": mid,
            "spread_pct": None if spread_pct is None else round(spread_pct, 1),
            "ivr": ivr,
            "oi": oi,
            "oi_delta": None,
            "be": None if mid is None or K is None else round(float(K) + float(mid), 2),
            "be_pct": None,
            "source": src,
            "date": date,
        }
        if spot and row["be"] is not None:
            try:
                row["be_pct"] = round(100.0 * (row["be"] / float(spot) - 1.0), 2)
            except Exception:
                pass
        ok = (
            # M: ivr is None is NOT a pass — missing IVR means we can't verify the IV
            # regime. Previously `ivr is None or ivr < IVR_MAX` let unknown-IV rows
            # through the filter as if they were low-IVR.
            (ivr is not None and ivr < IVR_MAX)
            and (spread_pct is not None and spread_pct < SPREAD_MAX_PCT)
            and oi >= OI_MIN
        )
        row["lights"] = _seven_lights(spread_pct, ivr, oi, mid)
        if ok:
            cands.append(row)
        else:
            near.append(row)
    cands = sorted(cands, key=lambda x: -(x.get("oi") or 0))[:3]
    near = sorted(
        near,
        key=lambda x: (
            0 if (x.get("spread_pct") or 99) < SPREAD_MAX_PCT else 1,
            -(x.get("oi") or 0),
        ),
    )[:5]
    return {
        "ok": True,
        "cards": cands,
        "near_miss": near,
        "rule": "IVR<25 & 价差<4% & OI>1万 & 昨OI增幅top10",
        "source": src,
        "note": (
            "POLYGON 未配置 → 仅用 workstation 链预筛;synthetic 链 OI 通常 <1万,"
            "故候选常为 0,near_miss 供看结构"
            if not POLYGON_KEY
            else "筛自 Polygon+OWS"
        ),
    }


def fetch_call_cards(ws: dict | None = None) -> dict:
    ws = ws if ws is not None else fetch_workstation()
    items = (ws or {}).get("items") or {}
    if not items:
        return {
            "ok": False,
            "error": "workstation 不可达且无 Polygon",
            "cards": [],
            "near_miss": [],
            "rule": "IVR<25 & 价差<4% & OI>1万 & 昨OI增幅top10",
        }
    # Polygon enrichment left for key; base cards from OWS chain always deterministic
    base = cards_from_ows(items)
    if not POLYGON_KEY:
        base["polygon"] = "BLOCKED"
        return base
    # With Polygon: prefer snapshot OI for SPY calls near spot
    try:
        spot = float(items.get("spot") or 0)
        url = (
            "https://api.polygon.io/v3/snapshot/options/SPY?limit=250&apiKey=%s"
            % POLYGON_KEY
        )
        data = http_get_json(url, timeout=40)
        enriched = []
        for r in data.get("results") or []:
            det = r.get("details") or {}
            if (det.get("contract_type") or "").lower() not in ("call", "c"):
                continue
            day = r.get("day") or {}
            quote = r.get("last_quote") or {}
            bid = quote.get("bid") or day.get("close")
            ask = quote.get("ask")
            mid = None
            if bid is not None and ask is not None:
                mid = (float(bid) + float(ask)) / 2
            elif day.get("close") is not None:
                mid = float(day["close"])
            oi = r.get("open_interest") or 0
            try:
                spread_pct = (
                    100.0 * (float(ask) - float(bid)) / float(mid)
                    if mid and ask is not None and bid is not None
                    else None
                )
            except Exception:
                spread_pct = None
            K = det.get("strike_price")
            ivr = items.get("ivr")
            if oi < OI_MIN:
                continue
            if spread_pct is None or spread_pct >= SPREAD_MAX_PCT:
                continue
            if ivr is not None and ivr >= IVR_MAX:
                continue
            if spot and K and abs(float(K) - spot) / spot > 0.08:
                continue
            be = None if mid is None or K is None else round(float(K) + float(mid), 2)
            enriched.append({
                "ul": "SPY",
                "expiry": _expiry_label(det.get("expiration_date"), None),
                "K": K,
                "cp": "C",
                "mid": None if mid is None else round(mid, 2),
                "spread_pct": None if spread_pct is None else round(spread_pct, 1),
                "ivr": ivr,
                "oi": oi,
                "oi_delta": None,
                "be": be,
                "be_pct": (
                    None
                    if be is None or not spot
                    else round(100.0 * (be / spot - 1.0), 2)
                ),
                "source": "polygon+ows_ivr",
                "lights": _seven_lights(spread_pct, ivr, oi, mid),
            })
        enriched = sorted(enriched, key=lambda x: -(x.get("oi") or 0))[:3]
        if enriched:
            base["cards"] = enriched
            base["polygon"] = "ok"
            base["note"] = "筛自 Polygon snapshot + OWS IVR"
            return base
        base["polygon"] = "ok_empty"
        base["note"] = "Polygon 已连但筛后 0 张;附 OWS near_miss"
        return base
    except Exception as e:
        base["polygon"] = "error"
        base["error"] = str(e)[:200]
        return base
