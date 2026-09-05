#!/usr/bin/env python3
"""build_universe.py · v1 (2026-08-25) — alpha-platform 8600 全市场单票宇宙(数据定义,不写票单)

宇宙定义(与 sp500_symbols.json 并列,不替代它;标普 BFS 段与 07-27 红线不动):
  全市场普通股(isEtf=false, isFund=false, isActivelyTrading=true, 交易所 NYSE/NASDAQ/AMEX)
  ∩ price ≥ UNIV_PRICE_MIN(默认 10)
  ∩ adv20 ≥ UNIV_DOLLAR_VOL_MIN(默认 5e7):daily_bars 综合量行 20 日均成交额(close×v,排除最新一根,src≠alpaca_iex)
    ——不读 screener/实时 quote 的 volume
  ∩ marketCap ≥ UNIV_MCAP_MIN(默认 3e8)
源:FMP stable /company-screener(一次调用,几千行;参数名与 legacy /stock-screener 同族)。
产物:UNIVERSE_PATH(默认 /data/universe_market.json)。
处决:raw_n < UNIV_MIN_RAW(默认 500)= 源失败/截断 → 退出码 2、不覆盖旧文件、不装数。

用法:
  python3 build_universe.py --selfcheck        # 只探端点(limit=5),打 HTTP 码+首行键名:她档位有没有 screener
  python3 build_universe.py                    # 正式生成
  python3 build_universe.py --fixture resp.json  # 离线:用一份已落盘的 screener 回包生成(冒烟用)
  python3 build_universe.py --dry-run          # 生成但不写盘,打统计
env:FMP_API_KEY FMP_BASE(默认 https://financialmodelingprep.com/stable) UNIVERSE_PATH
    UNIV_PRICE_MIN UNIV_DOLLAR_VOL_MIN UNIV_MCAP_MIN UNIV_MIN_RAW UNIV_EXCHANGES(默认 NYSE,NASDAQ,AMEX)
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

FMP_BASE = os.getenv("FMP_BASE", "https://financialmodelingprep.com/stable").rstrip("/")
OUT_PATH = os.getenv("UNIVERSE_PATH", "/data/universe_market.json")
PRICE_MIN = float(os.getenv("UNIV_PRICE_MIN", "10"))
DVOL_MIN = float(os.getenv("UNIV_DOLLAR_VOL_MIN", "50000000"))
MCAP_MIN = float(os.getenv("UNIV_MCAP_MIN", "300000000"))
MIN_RAW = int(os.getenv("UNIV_MIN_RAW", "500"))
EXCHANGES = [x.strip().upper() for x in os.getenv("UNIV_EXCHANGES", "NYSE,NASDAQ,AMEX").split(",") if x.strip()]
BAR_SRC_IEX = "alpaca_iex"
PLATFORM_DB = os.getenv("PLATFORM_DB", "/data/platform.db")


class UniverseError(RuntimeError):
    """CLI 转成 exit 2;scan 循环 catch 后保留旧文件。"""


def _key():
    k = os.getenv("FMP_API_KEY", "").strip()
    if not k:
        raise UniverseError("FMP_API_KEY 未设(worker .env 有,api 容器没有——本脚本在 worker 侧跑)")
    return k


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "alpha-universe/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def screener_url(limit):
    q = {
        "limit": limit,
        "isEtf": "false",
        "isFund": "false",
        "isActivelyTrading": "true",
        "priceMoreThan": int(PRICE_MIN),
        "exchange": ",".join(EXCHANGES),
        "apikey": _key(),
    }
    return FMP_BASE + "/company-screener?" + urllib.parse.urlencode(q)


def selfcheck():
    """探端点:HTTP 码 + 行数 + 首行键名。402/403 = 档位无 screener,走 SPEC 的回落路(stock-list+batch quote)。"""
    url = screener_url(5)
    try:
        code, body = _get(url)
    except urllib.error.HTTPError as e:
        print("[universe] selfcheck HTTP %s %s | %s" % (e.code, e.reason, e.read().decode(errors="replace")[:200]))
        return 1
    try:
        rows = json.loads(body)
    except Exception:
        print("[universe] selfcheck HTTP %s 非 JSON:%s" % (code, body[:200]))
        return 1
    if not isinstance(rows, list) or not rows:
        print("[universe] selfcheck HTTP %s 空表:%s" % (code, body[:200]))
        return 1
    print("[universe] selfcheck HTTP %s rows=%d keys=%s" % (code, len(rows), sorted(rows[0].keys())))
    need = {"symbol", "price", "volume", "marketCap", "isEtf", "exchangeShortName"}
    miss = need - set(rows[0].keys())
    print("[universe] 必需键:", "齐" if not miss else "缺 %s(回包形状与文档不符,先贴回再改解析)" % sorted(miss))
    return 0 if not miss else 1


def load_adv20_map(symbols: list[str], db_path: str | None = None) -> dict[str, tuple[float, int]]:
    """symbol → (adv20_dollar, last_composite_volume). 综合量不足 21 根则缺席。"""
    path = db_path or PLATFORM_DB
    out: dict[str, tuple[float, int]] = {}
    if not symbols or not os.path.isfile(path):
        return out
    con = sqlite3.connect(path, timeout=30)
    try:
        for i in range(0, len(symbols), 400):
            chunk = symbols[i : i + 400]
            q = (
                "WITH ranked AS ("
                " SELECT symbol, c, v, ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY ts DESC) AS rn"
                " FROM daily_bars WHERE symbol IN (%s) AND (src IS NULL OR src<>?)"
                ") SELECT symbol, c, v, rn FROM ranked WHERE rn <= 21"
                % ",".join("?" * len(chunk))
            )
            rows = con.execute(q, (*chunk, BAR_SRC_IEX)).fetchall()
            by: dict[str, list[tuple[int, float, float]]] = {}
            for sym, c, v, rn in rows:
                by.setdefault(str(sym).upper(), []).append((int(rn), float(c or 0), float(v or 0)))
            for sym, bars in by.items():
                bars.sort()
                if len(bars) < 21:
                    continue
                last_v = int(bars[0][2])  # rn=1 latest
                vals = [px * vol for _, px, vol in bars[1:21]]
                out[sym] = (sum(vals) / len(vals), last_v)
    finally:
        con.close()
    return out


def build(rows, adv20: dict[str, tuple[float, int]] | None = None):
    """rows = screener 回包.adv20 缺席或 < DVOL_MIN → 丢.不读 quote volume。"""
    dropped = {
        "etf_or_fund": 0, "inactive": 0, "exchange": 0, "price": 0,
        "dollar_vol": 0, "mcap": 0, "bad_row": 0,
    }
    seen, cand = set(), []
    for r in rows:
        try:
            sym = str(r.get("symbol") or "").upper().strip()
            if not sym or not sym.replace("-", "").replace(".", "").isalpha() or len(sym) > 6:
                dropped["bad_row"] += 1
                continue
            if r.get("isEtf") or r.get("isFund"):
                dropped["etf_or_fund"] += 1
                continue
            if r.get("isActivelyTrading") is False:
                dropped["inactive"] += 1
                continue
            ex = str(r.get("exchangeShortName") or r.get("exchange") or "").upper()
            if EXCHANGES and ex not in EXCHANGES:
                dropped["exchange"] += 1
                continue
            px, mc = float(r.get("price") or 0), float(r.get("marketCap") or 0)
            if px < PRICE_MIN:
                dropped["price"] += 1
                continue
            if mc < MCAP_MIN:
                dropped["mcap"] += 1
                continue
            if sym in seen:
                continue
            seen.add(sym)
            cand.append((sym, px, mc, ex, r))
        except Exception:
            dropped["bad_row"] += 1
    if adv20 is None:
        adv20 = load_adv20_map([s for s, *_ in cand])
    out = []
    for sym, px, mc, ex, r in cand:
        hit = adv20.get(sym)
        if not hit or hit[0] < DVOL_MIN:
            dropped["dollar_vol"] += 1
            continue
        adv, last_v = hit
        out.append({
            "symbol": sym,
            "price": round(px, 4),
            "volume": int(last_v),
            "dollar_vol": round(adv),
            "market_cap": round(mc),
            "exchange": ex,
            "sector": r.get("sector"),
            "industry": r.get("industry"),
            "adv20": round(adv),
        })
    out.sort(key=lambda x: -x["dollar_vol"])
    return out, dropped


def run_build(*, out: str, fixture: str | None = None, dry_run: bool = False) -> dict:
    """拉 screener → 过滤 → 写盘。失败 raise UniverseError,不覆盖旧文件。"""
    if fixture:
        rows = json.load(open(fixture, encoding="utf-8"))
        src = "fixture:" + fixture
        http = None
    else:
        try:
            http, body = _get(screener_url(10000))
        except urllib.error.HTTPError as e:
            raise UniverseError(
                "screener HTTP %s %s | %s(档位无此端点=走 SPEC 回落路;旧文件未动)"
                % (e.code, e.reason, e.read().decode(errors="replace")[:200])
            ) from e
        rows = json.loads(body)
        src = FMP_BASE + "/company-screener"
    if not isinstance(rows, list):
        raise UniverseError("回包不是 list:%s" % str(rows)[:200])
    raw_n = len(rows)
    if raw_n < MIN_RAW:
        raise UniverseError("处决:raw_n=%d < %d(源失败/截断),不写盘不装数" % (raw_n, MIN_RAW))
    univ, dropped = build(rows)
    now = time.time()
    doc = {
        "kind": "universe_market",
        "version": 1,
        "ts": now,
        "asof_et": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-4))).strftime("%Y-%m-%d %H:%M ET"),
        "source": src,
        "definition": {
            "price_min": PRICE_MIN,
            "dollar_vol_min": DVOL_MIN,
            "mcap_min": MCAP_MIN,
            "exchanges": EXCHANGES,
            "etf_fund": "excluded",
            "actively_trading": True,
            "adv20_min": DVOL_MIN,
            "adv20_src": "daily_bars composite src<>alpaca_iex exclude latest",
            "quote_volume": "not used",
        },
        "n": len(univ),
        "symbols": [x["symbol"] for x in univ],
        "rows": univ,
        "self_proof": {"http": http, "raw_n": raw_n, "dropped": dropped},
    }
    print("[universe] raw=%d → n=%d | dropped=%s | top5=%s" % (raw_n, len(univ), dropped, doc["symbols"][:5]))
    if dry_run:
        return doc
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    tmp = out + ".tmp"
    json.dump(doc, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, out)
    print("[universe] 写盘", out)
    return doc


def refresh_if_stale(*, max_age_h: float = 24.0, out: str | None = None) -> str:
    """Scan 循环调用:文件缺失或 ts 龄 > max_age_h 则重建。返回 skipped|refreshed|failed。不 sys.exit。"""
    path = out or os.getenv("UNIVERSE_MARKET_CACHE") or OUT_PATH
    age_h = None
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.loads(fh.read())
            ts = float(doc.get("ts") or 0)
            if ts:
                age_h = (time.time() - ts) / 3600.0
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            age_h = None
    if age_h is not None and age_h <= max_age_h:
        return "skipped"
    try:
        run_build(out=path)
        return "refreshed"
    except UniverseError as exc:
        print("[universe] refresh failed:", exc)
        return "failed"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selfcheck", action="store_true")
    ap.add_argument("--fixture", help="离线:已落盘的 screener 回包 JSON(list)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=OUT_PATH)
    a = ap.parse_args()
    if a.selfcheck:
        sys.exit(selfcheck())
    try:
        run_build(out=a.out, fixture=a.fixture, dry_run=a.dry_run)
    except UniverseError as exc:
        print("[universe]", exc)
        sys.exit(2)


if __name__ == "__main__":
    main()
