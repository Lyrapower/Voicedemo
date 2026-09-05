"""[已弃用 2026-08-17] alpaca_loader.py —— Alpaca 期权合约(OI)+行情 → OWS raw 快照(非 synthetic)。

弃用原因:RE CROSS PROJECT REVIEW v5 #2 —— OWS 期权数据走 theta only(单缝),Alpaca 期权 OI 质量不及 OPRA via theta。
当前状态:全仓零 import,未接线;theta 挂时 OWS 显"等待 Theta 数据"占位,不回退 Alpaca。
保留文件仅为历史参考,禁止重新接线为 theta 的 fallback(如需重启须 Lyra 逐字授权)。
raw 不可变:同日已存在则拒绝覆盖(与 theta_loader/datastore 纪律一致)。
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import Any
from zoneinfo import ZoneInfo

import datastore

_ET = ZoneInfo("America/New_York")  # trading-date logic uses ET (DST-aware)

try:
    import certifi

    def _ssl():
        return ssl.create_default_context(cafile=certifi.where())
except Exception:  # noqa: BLE001
    def _ssl():
        return ssl.create_default_context()


DTE_TARGETS = (7, 30, 60)
R_DEFAULT = float(os.getenv("OWS_R", "0.04"))
Q_DEFAULT = float(os.getenv("OWS_Q", "0.012"))
TRADE_API = os.getenv("ALPACA_TRADE_API", "https://paper-api.alpaca.markets").rstrip("/")
DATA_API = os.getenv("ALPACA_DATA_API", "https://data.alpaca.markets").rstrip("/")
FEED = os.getenv("ALPACA_OPTION_FEED", "indicative").strip() or "indicative"


def _load_keys() -> tuple[str, str]:
    key = os.getenv("ALPACA_API_KEY", "").strip()
    sec = os.getenv("ALPACA_SECRET_KEY", "").strip()
    if key and sec:
        return key, sec
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (
        os.path.join(here, "..", ".env"),
        os.path.join(here, "..", "..", "aether_nexus", ".env"),
        os.path.join(here, "..", "..", "grid-scout", ".env"),
    ):
        try:
            with open(path, encoding="utf-8") as f:
                found: dict[str, str] = {}
                for ln in f:
                    s = ln.strip()
                    if not s or s.startswith("#") or "=" not in s:
                        continue
                    k, _, v = s.partition("=")
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY") and v:
                        found[k] = v
                if found.get("ALPACA_API_KEY") and found.get("ALPACA_SECRET_KEY"):
                    return found["ALPACA_API_KEY"], found["ALPACA_SECRET_KEY"]
        except OSError:
            continue
    return "", ""


def _http_json(url: str, headers: dict[str, str], *, timeout: int = 60) -> Any:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl()) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _headers(key: str, sec: str) -> dict[str, str]:
    return {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": sec,
        "Accept": "application/json",
    }


def _fetch_contracts(root: str, key: str, sec: str, day: dt.date) -> list[dict[str, Any]]:
    """分页拉 active 合约(含 open_interest)。"""
    out: list[dict[str, Any]] = []
    page = None
    gte = day.isoformat()
    lte = (day + dt.timedelta(days=120)).isoformat()
    while True:
        q = {
            "underlying_symbols": root,
            "status": "active",
            "limit": 1000,
            "expiration_date_gte": gte,
            "expiration_date_lte": lte,
        }
        if page:
            q["page_token"] = page
        url = TRADE_API + "/v2/options/contracts?" + urllib.parse.urlencode(q)
        j = _http_json(url, _headers(key, sec))
        batch = j.get("option_contracts") or []
        out.extend(batch)
        page = j.get("next_page_token")
        if not page or not batch:
            break
        if len(out) >= 8000:
            break
    return out


def _fetch_quotes(symbols: list[str], key: str, sec: str) -> dict[str, dict[str, Any]]:
    """data API 批量 snapshot → symbol → {bid,ask,age_s}。"""
    out: dict[str, dict[str, Any]] = {}
    now = dt.datetime.now(dt.timezone.utc)
    for i in range(0, len(symbols), 80):
        chunk = symbols[i : i + 80]
        q = urllib.parse.urlencode({"symbols": ",".join(chunk), "feed": FEED})
        url = DATA_API + "/v1beta1/options/snapshots?" + q
        try:
            j = _http_json(url, _headers(key, sec), timeout=90)
        except Exception as e:  # noqa: BLE001
            print("[alpaca-ingest] snapshots batch fail:", e, file=sys.stderr)
            continue
        snaps = j.get("snapshots") or {}
        for sym, body in snaps.items():
            lq = (body or {}).get("latestQuote") or {}
            bid = float(lq.get("bp") or 0)
            ask = float(lq.get("ap") or 0)
            age = 0
            ts = lq.get("t")
            if ts:
                try:
                    t = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    age = max(0, int((now - t).total_seconds()))
                except Exception:  # noqa: BLE001
                    age = 0
            out[sym] = {"bid": bid, "ask": ask, "quote_age_s": age}
    return out


def _fetch_spot_hist(root: str, key: str, sec: str, day: dt.date) -> tuple[float, list[float]]:
    """日线收盘 hist_tail(21) + 最新 spot。"""
    start = (day - dt.timedelta(days=45)).isoformat()
    end = (day + dt.timedelta(days=1)).isoformat()
    q = urllib.parse.urlencode(
        {
            "timeframe": "1Day",
            "start": start + "T00:00:00Z",
            "end": end + "T23:59:59Z",
            "adjustment": "raw",
            "feed": os.getenv("ALPACA_DATA_FEED", "iex"),
            "limit": 50,
            # 必须 sort=desc:Alpaca 默认 asc+limit 会吃到 start 附近最旧日线
            "sort": "desc",
        }
    )
    url = f"{DATA_API}/v2/stocks/{root}/bars?{q}"
    j = _http_json(url, _headers(key, sec))
    bars = j.get("bars") or []
    # API desc → 时间正序再取尾部(spot=最新收盘)
    closes = list(
        reversed([float(b["c"]) for b in bars if b.get("c") is not None])
    )
    if not closes:
        raise RuntimeError("no stock bars for " + root)
    return closes[-1], closes[-21:]


def _pick_expiries(contracts: list[dict[str, Any]], day: dt.date) -> dict[int, tuple[str, int]]:
    """目标 DTE(7/30/60) → (expiration_date, 实际日历 dte)。
    快照里 dte 字段写目标桶(供 features atm_iv30 精确匹配),T 用实际日历。"""
    by_exp: dict[str, int] = {}
    for c in contracts:
        exp = c.get("expiration_date")
        if not exp:
            continue
        try:
            dte = (dt.date.fromisoformat(exp[:10]) - day).days
        except ValueError:
            continue
        if dte < 1:
            continue
        by_exp[exp[:10]] = dte
    picked: dict[int, tuple[str, int]] = {}
    used_exp: set[str] = set()
    for target in DTE_TARGETS:
        best = None
        best_dist = 10**9
        for exp, dte in by_exp.items():
            if exp in used_exp:
                continue
            dist = abs(dte - target)
            if dist < best_dist:
                best_dist, best = dist, (exp, dte)
        if best:
            used_exp.add(best[0])
            picked[target] = best
    return picked


def build_snapshot(root: str, date: str, *, key: str = "", sec: str = "") -> dict[str, Any]:
    key, sec = key or _load_keys()[0], sec or _load_keys()[1]
    if not (key and sec):
        key, sec = _load_keys()
    if not (key and sec):
        raise RuntimeError("ALPACA_API_KEY/SECRET 未配置")
    day = dt.date.fromisoformat(date)
    spot, hist = _fetch_spot_hist(root, key, sec, day)
    contracts = _fetch_contracts(root, key, sec, day)
    if not contracts:
        raise RuntimeError("no option contracts")
    picked = _pick_expiries(contracts, day)
    if not picked:
        raise RuntimeError("no expiries near 7/30/60")

    # 每到期 ATM±N 档,控制体量
    want_exps = {exp for exp, _ in picked.values()}
    by_exp_type: dict[str, dict[str, list]] = defaultdict(lambda: {"call": [], "put": []})
    for c in contracts:
        exp = (c.get("expiration_date") or "")[:10]
        if exp not in want_exps:
            continue
        cp = (c.get("type") or "").lower()
        if cp not in ("call", "put"):
            continue
        try:
            k = float(c.get("strike_price"))
        except (TypeError, ValueError):
            continue
        oi = c.get("open_interest")
        try:
            oi_i = int(float(oi)) if oi not in (None, "") else 0
        except (TypeError, ValueError):
            oi_i = 0
        by_exp_type[exp][cp].append(
            {"symbol": c["symbol"], "K": k, "oi": oi_i}
        )

    symbols: list[str] = []
    for exp, sides in by_exp_type.items():
        for cp in ("call", "put"):
            rows = sorted(sides[cp], key=lambda x: abs(x["K"] - spot))[:31]
            sides[cp] = rows
            symbols.extend(r["symbol"] for r in rows)
    quotes = _fetch_quotes(symbols, key, sec)

    expiries = []
    for target_dte, (exp, cal_dte) in sorted(picked.items(), key=lambda x: x[0]):
        T = max(cal_dte, 1) / 365.0
        calls = {r["K"]: r for r in by_exp_type[exp]["call"]}
        puts = {r["K"]: r for r in by_exp_type[exp]["put"]}
        ks = sorted(set(calls) | set(puts))
        strikes = []
        for K in ks:
            crow, prow = calls.get(K), puts.get(K)
            # M: previously dropped strikes missing one side (`if not crow or not prow:
            # continue`), thinning asymmetric chains. Keep the strike and fill the
            # missing leg with a zero-shell (cleaning isolates it), matching theta_loader.
            cq = quotes.get(crow["symbol"]) if crow else None
            pq = quotes.get(prow["symbol"]) if prow else None
            strikes.append(
                {
                    "K": K,
                    "call": {
                        "bid": round(float(cq["bid"]), 2) if cq else 0.0,
                        "ask": round(float(cq["ask"]), 2) if cq else 0.0,
                        "oi": int(crow["oi"]) if crow else 0,
                        "quote_age_s": int(cq.get("quote_age_s") or 0) if cq else 9999,
                    },
                    "put": {
                        "bid": round(float(pq["bid"]), 2) if pq else 0.0,
                        "ask": round(float(pq["ask"]), 2) if pq else 0.0,
                        "oi": int(prow["oi"]) if prow else 0,
                        "quote_age_s": int(pq.get("quote_age_s") or 0) if pq else 9999,
                    },
                }
            )
        if strikes:
            expiries.append({
                "dte": int(target_dte),
                "T": T,
                "strikes": strikes,
                "expiration": exp,
                "calendar_dte": int(cal_dte),
            })

    if not expiries:
        raise RuntimeError("no strikes after quote join")

    return {
        "date": date,
        "underlying": root,
        "spot": round(float(spot), 2),
        "r": R_DEFAULT,
        "q": Q_DEFAULT,
        "hist_tail": [round(x, 2) for x in hist],
        "expiries": expiries,
        "source": "alpaca-options-v1",
        "ts": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "notes": "OI from Alpaca contracts; quotes feed=%s; GEX 假设见 gex.py" % FEED,
    }


def ingest_day(root: str, date: str) -> str:
    snap = build_snapshot(root.upper(), date)
    path = os.path.join(datastore.RAW, date + ".json")
    datastore.save_raw(date, snap)
    n = sum(len(e["strikes"]) for e in snap["expiries"])
    print(
        f"[alpaca-ingest] {root} {date} spot={snap['spot']} "
        f"expiries={len(snap['expiries'])} strikes={n} → {path}"
    )
    return path


def main(argv: list[str] | None = None) -> int:
    import argparse

    # host default data dir
    if not os.getenv("OWS_DATA"):
        here = os.path.dirname(os.path.abspath(__file__))
        os.environ["OWS_DATA"] = os.path.abspath(os.path.join(here, "..", "data"))
        datastore.DATA_DIR = os.environ["OWS_DATA"]
        datastore.RAW = os.path.join(datastore.DATA_DIR, "raw")

    p = argparse.ArgumentParser(description="Alpaca options → option-workstation raw/")
    p.add_argument("--root", default="SPY")
    p.add_argument("--date", help="YYYY-MM-DD;默认今日(周末回退)")
    args = p.parse_args(argv)
    date = args.date or dt.datetime.now(_ET).date().isoformat()
    d = dt.date.fromisoformat(date)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    date = d.isoformat()
    try:
        ingest_day(args.root.upper(), date)
    except Exception as e:  # noqa: BLE001
        print("[alpaca-ingest] FAIL:", e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
