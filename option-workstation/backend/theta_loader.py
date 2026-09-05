"""theta_loader.py —— Theta v3 EOD → OWS raw 快照(与 datastore.gen_synthetic 同结构)。

v3:OI 在独立端点 /v3/option/history/open_interest(EOD 价格端点不返回 OI 列);
build_snapshot 双拉 EOD 价格 + OI,按 (exp, strike, side) 合并。
raw 不可变:同日已存在则拒绝覆盖。
"""
from __future__ import annotations

import datetime as dt
import math
import os
import sys
from collections import defaultdict
from typing import Any
from zoneinfo import ZoneInfo

import datastore
import theta_client

_ET = ZoneInfo("America/New_York")  # trading-date logic uses ET (DST-aware)

# Theta v2 strike 多为「美元×1000」(140000 → $140)
STRIKE_DIV = float(os.getenv("THETA_STRIKE_DIV", "1000"))
# 目标 DTE 桶(与合成器对齐);取最接近的到期
DTE_TARGETS = (7, 30, 60)
R_DEFAULT = float(os.getenv("OWS_R", "0.04"))
Q_DEFAULT = float(os.getenv("OWS_Q", "0.012"))


def _ymd_int(date: str) -> int:
    return int(date.replace("-", ""))


def _parse_date(d: Any) -> str | None:
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


def _strike_dollars(raw: Any) -> float | None:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    # 已是美元尺度(如 500.0)则不再除
    if v < 10000:
        return round(v, 4)
    return round(v / STRIKE_DIV, 4)


def _tick_row(fmt: list[str] | None, tick: list[Any] | dict[str, Any]) -> dict[str, Any]:
    if isinstance(tick, dict):
        return tick
    if not fmt:
        # 文档默认顺序
        keys = [
            "ms_of_day", "ms_of_day2", "open", "high", "low", "close", "volume", "count",
            "bid_size", "bid_exchange", "bid", "bid_condition",
            "ask_size", "ask_exchange", "ask", "ask_condition", "date",
        ]
    else:
        keys = list(fmt)
    out = {}
    for i, k in enumerate(keys):
        if i < len(tick):
            out[k] = tick[i]
    return out


def _iter_contracts(payload: Any) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """→ [(contract, quote_row), ...]"""
    out: list[tuple[dict[str, Any], dict[str, Any]]] = []
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
                    # 取末日/最后一条
                    row = _tick_row(fmt, ticks[-1])
                    out.append((contract, row))
                elif any(k in item for k in ("bid", "ask", "close")):
                    out.append((contract or item, item))
        return out
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and "contract" in item:
                out.extend(_iter_contracts(item))
            elif isinstance(item, dict):
                out.append((item, item))
    return out


def _spot_from_stock(payload: Any) -> float | None:
    if not payload:
        return None
    rows = []
    if isinstance(payload, dict):
        resp = payload.get("response") or payload.get("data") or payload.get("ticks")
        if isinstance(resp, list):
            rows = resp
        elif "close" in payload:
            try:
                return float(payload["close"])
            except (TypeError, ValueError):
                return None
    for r in rows:
        if isinstance(r, dict) and r.get("close") is not None:
            try:
                return float(r["close"])
            except (TypeError, ValueError):
                continue
        if isinstance(r, (list, tuple)) and len(r) >= 6:
            try:
                return float(r[5])  # close 常见第 6 列
            except (TypeError, ValueError):
                continue
    return None


def _quote_side(row: dict[str, Any], *, oi: int | None = None) -> dict[str, Any]:
    bid = float(row.get("bid") or 0)
    ask = float(row.get("ask") or 0)
    quote_stale = False
    if ask <= 0 and row.get("close") is not None:
        # M: close-as-mid fallback produces a zero-spread synthetic quote that can pass
        # cleaning as if it were a tight live quote. Mark stale and impose a nominal
        # spread so downstream spread/greeks don't silently treat it as a real quote.
        mid = float(row["close"])
        spread = max(mid * 0.01, 0.05)  # nominal 1% (min 5¢) — clearly not a live quote
        bid = mid - spread / 2
        ask = mid + spread / 2
        quote_stale = True
    if oi is None:
        oi = int(row.get("open_interest") or row.get("oi") or 0)
    return {
        "bid": round(max(0.0, bid), 4),
        "ask": round(max(0.0, ask), 4),
        "oi": oi,
        "quote_age_s": 0,
        "quote_stale": quote_stale,
    }


def _oi_map(payload: Any) -> dict[tuple[str, float, str], int]:
    """v3 /v3/option/history/open_interest 响应 → {(expiration, strike, side): oi}。

    OI 由 OPRA 每日 ~06:30 ET 报告一次(代表前一交易日收盘 OI);取每合约 data 末条。
    """
    out: dict[tuple[str, float, str], int] = {}
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


def build_snapshot(
    root: str,
    date: str,
    *,
    base: str | None = None,
    r: float = R_DEFAULT,
    q: float = Q_DEFAULT,
) -> dict[str, Any]:
    ymd = _ymd_int(date)
    asof = dt.date.fromisoformat(date)
    stock = theta_client.stock_eod(root, ymd, base=base)
    spot = _spot_from_stock(stock)
    spot_source = "stock_eod" if spot is not None else "missing"
    # O2: fetch a real ≥21-close history for RV20/VRP20 (was [spot] only → VRP20 always null).
    hist_closes = theta_client.stock_eod_series(root, ymd, days=45, base=base)
    bulk = theta_client.bulk_option_eod(root, ymd, exp=0, base=base)
    pairs = _iter_contracts(bulk)
    if not pairs:
        raise RuntimeError(f"Theta 无合约行: {root} {date}")

    # v3: OI 在独立端点(EOD 价格端点不返回 OI 列)。双拉后按 (exp, strike, side) 合并。
    oi_payload = None
    try:
        oi_payload = theta_client.option_history_open_interest(root, ymd, base=base)
    except Exception:  # noqa: BLE001
        oi_payload = None
    oi_map = _oi_map(oi_payload)
    oi_available = bool(oi_map)

    # exp_yyyymmdd → strike → {call,put}
    by_exp: dict[str, dict[float, dict[str, Any]]] = defaultdict(lambda: defaultdict(dict))
    for contract, row in pairs:
        exp_s = _parse_date(contract.get("expiration") or contract.get("exp") or row.get("expiration"))
        if not exp_s:
            continue
        K = _strike_dollars(contract.get("strike") or row.get("strike"))
        if K is None:
            continue
        right = str(contract.get("right") or row.get("right") or "").upper()
        side = "call" if right in ("C", "CALL") else ("put" if right in ("P", "PUT") else "")
        if not side:
            continue
        oi_val = oi_map.get((exp_s, K, side)) if oi_available else None
        by_exp[exp_s][K][side] = _quote_side(row, oi=oi_val)

    if spot is None:
        # O4: 用 ATM 附近 call/put mid 反推粗糙 spot(仅兜底)——但标记为 strike 代理,
        # 不是市场 spot,让消费侧知道 spot_unverified。不再静默把行权价当市场价。
        for exp_s, strikes in by_exp.items():
            for K, legs in strikes.items():
                c, p = legs.get("call"), legs.get("put")
                if c and p and c["ask"] > 0 and p["ask"] > 0:
                    spot = K
                    spot_source = "strike_proxy_unverified"
                    break
            if spot:
                break
    if spot is None:
        raise RuntimeError("无法得到 spot(股票 EOD 与链均无)")

    # 选最接近 7/30/60 的到期
    exp_dates = sorted(by_exp.keys())
    chosen: list[tuple[int, str]] = []
    for target in DTE_TARGETS:
        best = None
        best_d = 10**9
        for exp_s in exp_dates:
            dte = (dt.date.fromisoformat(exp_s) - asof).days
            if dte <= 0:
                continue
            dist = abs(dte - target)
            if dist < best_d:
                best_d = dist
                best = (dte, exp_s)
        if best and best not in chosen:
            chosen.append(best)
    if not chosen:
        # 退而取最近 3 个正 DTE
        for exp_s in exp_dates:
            dte = (dt.date.fromisoformat(exp_s) - asof).days
            if dte > 0:
                chosen.append((dte, exp_s))
            if len(chosen) >= 3:
                break

    expiries = []
    for dte, exp_s in chosen:
        T = max(dte, 1) / 365.0
        strikes_out = []
        for K in sorted(by_exp[exp_s].keys()):
            legs = by_exp[exp_s][K]
            if "call" not in legs and "put" not in legs:
                continue
            row = {"K": K}
            if "call" in legs:
                row["call"] = legs["call"]
            if "put" in legs:
                row["put"] = legs["put"]
            # 缺一边时补空壳(清洗会隔离)
            row.setdefault("call", {"bid": 0.0, "ask": 0.0, "oi": 0, "quote_age_s": 0})
            row.setdefault("put", {"bid": 0.0, "ask": 0.0, "oi": 0, "quote_age_s": 0})
            strikes_out.append(row)
        if strikes_out:
            expiries.append({"dte": dte, "T": T, "expiry": exp_s, "strikes": strikes_out})

    if not expiries:
        raise RuntimeError("无可用到期桶")

    notes = [
        "source=thetadata-eod",
        f"theta_base={theta_client.DEFAULT_BASE}",
    ]
    if oi_available:
        notes.append(f"oi_source=v3/option/history/open_interest ({len(oi_map)} contracts)")
    else:
        notes.append("oi_source=missing(OI 端点无数据 → oi=0,GEX 不可信)")
    # O2: build a real hist_tail from the fetched close series (ascending, capped).
    # Fall back to [spot] only if the series fetch returned nothing.
    if hist_closes:
        hist_tail = [round(float(c), 4) for c in hist_closes[-30:]]
    else:
        hist_tail = [round(float(spot), 4)]
        notes.append("hist_tail=1pt(无 EOD 序列)→RV20/VRP20 不可用")
    return {
        "date": date,
        "underlying": root.upper(),
        "spot": round(float(spot), 4),
        "spot_source": spot_source,
        "spot_unverified": spot_source == "strike_proxy_unverified",
        "r": r,
        "q": q,
        "hist_tail": hist_tail,
        "expiries": expiries,
        "source": "thetadata-eod",
        "ts": date + "T17:15:00-04:00",
        "notes": notes,
    }


def ingest_day(root: str, date: str, *, base: str | None = None, force_note: bool = False) -> str:
    snap = build_snapshot(root, date, base=base)
    path = os.path.join(datastore._root_dir(root), date + ".json")
    if os.path.exists(path):
        raise RuntimeError("raw 已存在,拒绝覆盖: " + root + " " + date + " (删文件或换日)")
    datastore.save_raw(date, snap, root=root)
    n_strikes = sum(len(e["strikes"]) for e in snap["expiries"])
    print(
        f"[theta-ingest] {root} {date} spot={snap['spot']} "
        f"expiries={len(snap['expiries'])} strikes={n_strikes} → {path}"
    )
    return path


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Theta EOD → option-workstation raw/")
    p.add_argument("--root", default="SPY", help="标的(P0: SPY/QQQ)")
    p.add_argument("--date", help="YYYY-MM-DD;默认最近交易日启发式(日历日-1)")
    p.add_argument("--base", default=None, help="Theta Terminal base URL")
    p.add_argument("--ping", action="store_true", help="只探测 Terminal")
    args = p.parse_args(argv)
    if args.base:
        os.environ["THETA_BASE"] = args.base
        theta_client.DEFAULT_BASE = args.base.rstrip("/")
    if args.ping:
        print(theta_client.ping(args.base))
        return 0
    date = args.date or (dt.datetime.now(_ET).date() - dt.timedelta(days=1)).isoformat()
    # 周末回退
    d = dt.date.fromisoformat(date)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    date = d.isoformat()
    st = theta_client.ping(args.base)
    if not st.get("ok"):
        print("[theta-ingest] Terminal 不可达:", st, file=sys.stderr)
        return 2
    try:
        ingest_day(args.root.upper(), date, base=args.base)
    except Exception as e:  # noqa: BLE001
        print("[theta-ingest] FAIL:", e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
