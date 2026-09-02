"""Factor Truth · deterministic SP500 movers + env factor percentiles (zero LLM)."""
from __future__ import annotations

import datetime as dt
import json
import logging
import math
import os
import statistics
import time
from io import BytesIO
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import sqlite3

# FMP key 不进 INFO 日志(httpx INFO 会把含 apikey= 的 URL 整行打出;2026-09-02 砥 P0)
logging.getLogger("httpx").setLevel(logging.WARNING)

import db
from alpaca_bars import bars_params

log = logging.getLogger("factor_truth")
ET = ZoneInfo("America/New_York")
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
SP500_CACHE = os.getenv("SP500_SYMBOLS_CACHE", "/data/sp500_symbols.json")
MOVERS_TOP = int(os.getenv("DAILY_MOVERS_TOP", "20"))
SP500_BATCH = int(os.getenv("SP500_ALPACA_BATCH", "10"))
DAILY_BAR_LIMIT = int(os.getenv("DAILY_BAR_LIMIT", "25"))
INITIAL_BAR_DAYS = int(os.getenv("DAILY_BAR_INITIAL_WINDOW", "30"))
UNIVERSE_CACHE = os.getenv("UNIVERSE_MARKET_CACHE", "/data/universe_market.json")
UNIV_BARS_PER_TICK = int(os.getenv("UNIV_BARS_PER_TICK", "150"))
MOVERS_PRICE_MIN = float(os.getenv("MOVERS_PRICE_MIN", "10"))
MOVERS_ADV20_MIN = float(os.getenv("MOVERS_ADV20_MIN", "100000000"))
RTH_OPEN = dt.time(9, 30)
RTH_CLOSE = dt.time(16, 0)
ETF_DENY_MOVERS = frozenset({"IBIT", "BITO", "TSLL", "SOXL", "SPY", "QQQ"})
# v2(守恒 8-25 审):新鲜度不能只看"最新 bar 日期"——还要看"上次抓取是什么时候、抓到的是不是收盘后的行"。
# 只看日期的两种坏法:①FMP EOD 盘中回当日部分 bar → 首拍存入后全天/隔夜都算"fresh",收盘价永远是 09:35 快照;
# ②FMP 盘中不回当日行 → RTH 每拍全宇宙重拉(78 拍×1768 票)。节假日同理:last_closed 没有 bar,整晚重拉。
RTH_REFRESH_S = int(os.getenv("RTH_REFRESH_S", "1800"))          # 盘中同一票最多每 30 分钟重拉一次
OFFHOURS_COOLDOWN_S = int(os.getenv("OFFHOURS_COOLDOWN_S", "7200"))  # 盘外缺 bar(节假日/数据滞后)每 2 小时试一次
FINAL_PASS_AFTER_S = int(os.getenv("FINAL_PASS_AFTER_S", "1800"))    # 收盘后 30 分钟起做一次"终盘补拉"(替换盘中部分 bar)
GAP_BREAKER_MIN = int(os.getenv("GAP_BREAKER_MIN", "200"))           # 缺 bar 票数 ≥ 此值触发断路器
GAP_PROBE_N = int(os.getenv("GAP_PROBE_N", "10"))                    # 断路器探测票数
# v2.2(Lyra 2026-08-25 拍板:盘中同日 movers,走 FMP quote):EOD 端点盘中没有当日行,同日 movers 只能来自 quote。
# 同一 key 同一档位(Scout 每班在打 /stable/quote),不加钱。盘中按 QUOTE_REFRESH_S 轮刷,每拍最多 QUOTE_PER_TICK 票,
# 最久未刷优先;movers 行有当日新鲜 quote 用 quote(source=quote),否则回落 EOD bar(source=eod)。
INTRADAY_QUOTES = os.getenv("INTRADAY_QUOTES", "1") == "1"
QUOTE_REFRESH_S = int(os.getenv("QUOTE_REFRESH_S", "1800"))
QUOTE_PER_TICK = int(os.getenv("QUOTE_PER_TICK", "300"))
QUOTE_STALE_S = int(os.getenv("QUOTE_STALE_S", "7200"))   # v2.3:2h——盖住 16:00→终盘补拉完成(≈17:15)的空窗,热力 movers 席不断档

# 源序(以代码为准,v2.5 修正过时注释):FMP premium 主源,Alpaca 备份只补 FMP 空的票。
# 原因不只是配额:Alpaca 免费档 feed=iex 的 volume 只是 IEX 一家交易所的量(消费者综合量的零头),
# 用它算 20 日成交额地板会把好票整批误杀;FMP 给的是综合量。故 Alpaca 补进来的 bar 记 src='alpaca_iex',
# adv20 只用综合量行(src 非 iex)算,综合量行不足 20 根 = 无实测,地板不过(不装数)。
FMP_API_KEY = os.getenv("FMP_API_KEY", "").strip()
FMP_BASE = os.getenv("FMP_BASE", "https://financialmodelingprep.com/stable").rstrip("/")

BAR_SRC_IEX = "alpaca_iex"


def _now_et() -> dt.datetime:
    """单一时钟入口(测试可覆盖)。"""
    return dt.datetime.now(ET)


def _log_attempt(c, sym: str, got: bool, now_ts: int | None = None) -> None:
    """记一次抓取尝试;got=True 时同步 got_ts(最近一次真拿到 bar 的时刻)。INSERT OR IGNORE + UPDATE,不依赖 upsert 语法。"""
    ts = int(now_ts if now_ts is not None else _now_et().timestamp())   # 与 needs_pull 同一时钟
    c.execute("INSERT OR IGNORE INTO bar_fetch_log(symbol, attempted_ts, got_ts) VALUES(?,?,NULL)", (sym, ts))
    if got:
        c.execute("UPDATE bar_fetch_log SET attempted_ts=?, got_ts=? WHERE symbol=?", (ts, ts, sym))
    else:
        c.execute("UPDATE bar_fetch_log SET attempted_ts=? WHERE symbol=?", (ts, sym))


def _fetch_log(c, sym: str) -> tuple[int, int]:
    row = c.execute("SELECT attempted_ts, got_ts FROM bar_fetch_log WHERE symbol=?", (sym,)).fetchone()
    if not row:
        return 0, 0
    return int(row[0] or 0), int(row[1] or 0)


def ensure_schema(c) -> None:
    c.executescript(db.SCHEMA)
    try:   # v2.5:bar 来源列(旧库 ALTER 一次;已有列则报错忽略)。旧行 src=NULL 视为综合量(历史全走 FMP)
        c.execute("ALTER TABLE daily_bars ADD COLUMN src TEXT")
    except sqlite3.OperationalError:
        pass


def _store_daily_bars(c, canonical: str, bars: list, src: str = "fmp") -> int:
    n = 0
    for b in bars:
        ts = int(dt.datetime.fromisoformat(b["t"].replace("Z", "+00:00")).timestamp())
        c.execute(
            "INSERT OR REPLACE INTO daily_bars(ts, symbol, o, h, l, c, v, src) VALUES(?,?,?,?,?,?,?,?)",
            (ts, canonical, b["o"], b["h"], b["l"], b["c"], b["v"], src),
        )
        n += 1
    return n


_fmp_get_day: str | None = None
_fmp_get_count: int = 0


def fmp_get_count_today() -> int:
    """In-process FMP single-symbol GET counter (reset ET midnight). V8 probe."""
    return _fmp_get_count


def _bump_fmp_get(n: int = 1) -> None:
    global _fmp_get_day, _fmp_get_count
    day = dt.datetime.now(ET).date().isoformat()
    if _fmp_get_day != day:
        _fmp_get_day = day
        _fmp_get_count = 0
    _fmp_get_count += n


def fetch_fmp_daily_bars(
    symbol: str,
    limit: int = DAILY_BAR_LIMIT,
    *,
    from_date: dt.date | None = None,
) -> list[dict]:
    """FMP stable /historical-price-eod/full → Alpaca 形 bars[{t,o,h,l,c,v}]。
    t = ET 午夜 ISO(与 Alpaca 1Day ts 约定一致);失败返 []。"""
    if not FMP_API_KEY:
        return []
    try:
        end = _now_et().date()
        if from_date is None:
            start = end - dt.timedelta(days=max(INITIAL_BAR_DAYS, limit + 5))
        else:
            start = from_date
            if start > end:
                return []
        _bump_fmp_get()
        r = httpx.get(
            f"{FMP_BASE}/historical-price-eod/full",
            params={"symbol": symbol, "from": start.isoformat(), "to": end.isoformat(), "apikey": FMP_API_KEY},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            return []
        out = []
        for h in data:
            try:
                d = dt.date.fromisoformat(str(h.get("date", ""))[:10])
                if from_date and d < from_date:
                    continue
                t_iso = dt.datetime(d.year, d.month, d.day, tzinfo=ET).isoformat()
                out.append({"t": t_iso, "o": float(h["open"]), "h": float(h["high"]),
                            "l": float(h["low"]), "c": float(h["close"]), "v": float(h.get("volume") or 0)})
            except (KeyError, TypeError, ValueError):
                continue
        out.sort(key=lambda b: b["t"])
        if limit and len(out) > limit:
            out = out[-limit:]
        return out
    except Exception as exc:
        log.debug("fmp daily skip %s: %s", symbol, exc)
        return []


def load_sp500_symbols(*, force: bool = False) -> list[str]:
    """Wikipedia S&P500 list, cached 24h on disk."""
    if not force and os.path.isfile(SP500_CACHE):
        try:
            cached = json.loads(open(SP500_CACHE, encoding="utf-8").read())
            if cached.get("symbols") and (time.time() - float(cached.get("ts", 0))) < 86400:
                return list(cached["symbols"])
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    try:
        import pandas as pd

        with httpx.Client(timeout=30, follow_redirects=True) as cli:
            r = cli.get(SP500_URL, headers={"User-Agent": "AlphaPlatform/1.0"})
            r.raise_for_status()
            tables = pd.read_html(BytesIO(r.content))
        df = tables[0]
        col = "Symbol" if "Symbol" in df.columns else df.columns[0]
        syms = [str(s).strip().upper().replace(".", "-") for s in df[col].tolist() if str(s).strip()]
        syms = [s for s in syms if s and s not in db.SURFACE_DENY]
        os.makedirs(os.path.dirname(SP500_CACHE) or ".", exist_ok=True)
        with open(SP500_CACHE, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "symbols": syms}, f)
        log.info("sp500 symbols loaded: %d", len(syms))
        return syms
    except Exception as exc:
        log.warning("sp500 load failed: %s", exc)
        try:
            with httpx.Client(timeout=30, follow_redirects=True) as cli:
                r = cli.get(SP500_URL, headers={"User-Agent": "AlphaPlatform/1.0"})
                r.raise_for_status()
                import re
                # Wikipedia first table: tickers like AAPL, BRK.B → BRK-B
                raw = re.findall(
                    r"data-sort-value=\"[^\"]*\"><a[^>]*>([A-Z][A-Z0-9.-]{0,6})</a>",
                    r.text,
                )
                syms = [s.strip().upper().replace(".", "-") for s in raw if s.strip()]
                syms = [s for s in dict.fromkeys(syms) if s and s not in db.SURFACE_DENY]
                if len(syms) >= 400:
                    os.makedirs(os.path.dirname(SP500_CACHE) or ".", exist_ok=True)
                    with open(SP500_CACHE, "w", encoding="utf-8") as f:
                        json.dump({"ts": time.time(), "symbols": syms}, f)
                    log.info("sp500 regex fallback: %d", len(syms))
                    return syms
        except Exception as exc2:
            log.warning("sp500 regex fallback failed: %s", exc2)
        if os.path.isfile(SP500_CACHE):
            try:
                return list(json.loads(open(SP500_CACHE, encoding="utf-8").read()).get("symbols") or [])
            except Exception:
                pass
        return []


def _get_state(c, key: str) -> dict[str, Any] | None:
    row = c.execute("SELECT value FROM platform_state WHERE key=?", (key,)).fetchone()
    if not row:
        return None
    try:
        val = json.loads(row[0])
        return val if isinstance(val, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _set_state(c, key: str, value: dict[str, Any]) -> None:
    c.execute(
        "INSERT OR REPLACE INTO platform_state(key, value, updated_ts) VALUES(?,?,?)",
        (key, json.dumps(value, ensure_ascii=False), int(time.time())),
    )


def _persist_fmp_get_count(c) -> None:
    day = dt.datetime.now(ET).date().isoformat()
    _set_state(c, "fmp_daily_gets", {"day": day, "count": fmp_get_count_today()})


def load_universe_market(*, force: bool = False) -> dict[str, Any] | None:
    """TTL 24h read /data/universe_market.json. Missing file → None + log; no sp500 fallback."""
    if not force and os.path.isfile(UNIVERSE_CACHE):
        try:
            cached = json.loads(open(UNIVERSE_CACHE, encoding="utf-8").read())
            if cached.get("kind") == "universe_market" and (time.time() - float(cached.get("ts", 0))) < 86400:
                cached["_age_h"] = round((time.time() - float(cached.get("ts", 0))) / 3600.0, 1)
                return cached
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    if not os.path.isfile(UNIVERSE_CACHE):
        log.warning("universe_market.json missing — empty universe (no sp500 fallback)")
        return None
    try:
        doc = json.loads(open(UNIVERSE_CACHE, encoding="utf-8").read())
        if doc.get("kind") != "universe_market":
            log.warning("universe_market.json invalid kind=%s", doc.get("kind"))
            return None
        age_h = (time.time() - float(doc.get("ts", 0))) / 3600.0
        doc["_age_h"] = round(age_h, 1)
        if age_h > 36:
            log.warning("universe_market.json stale: age=%.1fh (build_universe 未按日刷新)", age_h)
        return doc
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("universe_market.json unreadable: %s", exc)
        return None


def _session_day_bounds(day: dt.date | None = None) -> tuple[int, int]:
    """ET calendar-day [start, end) used by Alpaca 1Day bar timestamps (midnight ET)."""
    d = day or dt.datetime.now(ET).date()
    start = dt.datetime.combine(d, dt.time(0, 0), tzinfo=ET)
    end = start + dt.timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp())


def _is_rth(now: dt.datetime | None = None) -> bool:
    now = now or _now_et()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return RTH_OPEN <= t < RTH_CLOSE


def _last_closed_trading_day(ref: dt.date | None = None, now: dt.datetime | None = None) -> dt.date:
    """Previous ET session that has fully closed (weekends skipped; holidays handled by cooldown in needs_pull)."""
    now = now or _now_et()
    d = ref or now.date()
    if d == now.date() and now.time() < RTH_CLOSE:
        d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def _latest_bar_date(c, sym: str) -> dt.date | None:
    row = c.execute(
        "SELECT ts FROM daily_bars WHERE symbol=? ORDER BY ts DESC LIMIT 1", (sym,)
    ).fetchone()
    if not row:
        return None
    return dt.datetime.fromtimestamp(int(row[0]), tz=ET).date()


def _session_close_ts(day: dt.date) -> int:
    return int(dt.datetime.combine(day, RTH_CLOSE, tzinfo=ET).timestamp())


def needs_pull(c, sym: str, *, now: dt.datetime | None = None) -> tuple[bool, str]:
    """§0 v2:要不要拉,连同原因(机械判据,可审):
    无 bar             → 拉,但同一票 OFFHOURS_COOLDOWN_S 内只试一次(死票不无限重试)
    盘中(RTH)          → 同一票 RTH_REFRESH_S 内只拉一次(有当日行=定时刷新;无当日行=冷却重试)
    盘外,最新=上一收盘日 → 若该 bar 是盘中抓的(got_ts < 收盘+FINAL_PASS_AFTER_S)则收盘后做一次终盘补拉,否则 fresh
    盘外,最新<上一收盘日 → 节假日/数据滞后:OFFHOURS_COOLDOWN_S 冷却重试
    盘外,最新>上一收盘日 → fresh(不该发生,保守跳过)"""
    now = now or _now_et()
    now_ts = int(now.timestamp())
    latest = _latest_bar_date(c, sym)
    att, got = _fetch_log(c, sym)
    if latest is None:
        return (now_ts - att >= OFFHOURS_COOLDOWN_S), "no_bars"
    # 市场级断路器状态:断路器触发后写 until,窗口内"缺目标日 bar"类理由整体不出击(分片每拍换 150 票,
    # 光靠每票尝试记录压不住:每拍仍探 10 票;市场级一记,每 30 分钟全市场只探一次)
    brk = _get_state(c, "gap_breaker") or {}
    brk_until = int(brk.get("until", 0) or 0)
    if _is_rth(now):
        if latest >= now.date():
            return (now_ts - att) >= RTH_REFRESH_S, "rth_refresh"
        if brk_until > now_ts:
            return False, "rth_missing_today"
        return (now_ts - att) >= RTH_REFRESH_S, "rth_missing_today"
    target = _last_closed_trading_day(now.date(), now)
    if latest > target:
        return False, "ahead"
    if latest == target:
        final_ts = _session_close_ts(target) + FINAL_PASS_AFTER_S
        if now_ts >= final_ts and got and got < final_ts:
            return (now_ts - att >= 600), "final_close_pass"
        return False, "fresh"
    if brk_until > now_ts:
        return False, "gap_cooldown"
    return (now_ts - att >= OFFHOURS_COOLDOWN_S), "gap_cooldown"


def has_fresh_daily_bar(c, sym: str, *, now: dt.datetime | None = None) -> bool:
    """§0: 与 needs_pull 互补(保留旧调用名)。"""
    return not needs_pull(c, sym, now=now)[0]


def has_session_daily_bar(c, sym: str, day: dt.date | None = None) -> bool:
    """Deprecated alias — use has_fresh_daily_bar (§0 universe expansion)."""
    return has_fresh_daily_bar(c, sym)


def fetch_fmp_quote(symbol: str) -> dict[str, Any] | None:
    """FMP stable /quote?symbol= → {price, prev_close, volume, quote_ts}。字段形状 = Scout 现场每班在用的同一回包
    (price / previousClose / volume / timestamp);失败返 None。"""
    if not FMP_API_KEY:
        return None
    try:
        _bump_fmp_get()
        r = httpx.get(f"{FMP_BASE}/quote", params={"symbol": symbol, "apikey": FMP_API_KEY}, timeout=15)
        r.raise_for_status()
        data = r.json()
        row = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else None)
        if not row or row.get("price") in (None, 0):
            return None
        return {"price": float(row["price"]), "prev_close": float(row.get("previousClose") or 0) or None,
                "volume": float(row.get("volume") or 0), "quote_ts": int(row.get("timestamp") or _now_et().timestamp())}
    except Exception as exc:
        log.debug("fmp quote skip %s: %s", symbol, exc)
        return None


def refresh_intraday_quotes(c, symbols: list[str], *, deadline: float | None = None) -> int:
    """盘中轮刷 quote:只在 RTH;每票 QUOTE_REFRESH_S 内刷一次;每拍最多 QUOTE_PER_TICK,最久未刷优先。返回刷新票数。"""
    if not (INTRADAY_QUOTES and FMP_API_KEY and _is_rth()):
        return 0
    now_ts = int(_now_et().timestamp())
    uniq = list(dict.fromkeys(symbols))
    ensure_schema(c)     # v2.4:表由本模块 DDL 兜底,不依赖镜像里 db.py 的建表
    fetched = {r[0]: int(r[1] or 0) for r in c.execute("SELECT symbol, fetched_ts FROM intraday_quotes").fetchall()}
    due = [s for s in uniq if now_ts - fetched.get(s, 0) >= QUOTE_REFRESH_S]
    due.sort(key=lambda s: fetched.get(s, 0))
    n = 0
    for s in due[:QUOTE_PER_TICK]:
        if deadline is not None and time.time() >= deadline:
            break
        q = fetch_fmp_quote(s)
        if q:
            c.execute("INSERT OR REPLACE INTO intraday_quotes(symbol, price, prev_close, volume, quote_ts, fetched_ts) VALUES(?,?,?,?,?,?)",
                      (s, q["price"], q["prev_close"], q["volume"], q["quote_ts"], now_ts))
            n += 1
        else:
            c.execute("INSERT OR IGNORE INTO intraday_quotes(symbol, fetched_ts) VALUES(?,?)", (s, now_ts))
            c.execute("UPDATE intraday_quotes SET fetched_ts=? WHERE symbol=?", (now_ts, s))
    if due:
        log.info("intraday_quotes: refreshed %d / due %d / universe %d", n, len(due), len(uniq))
    return n


def _fresh_quote(c, sym: str, now: dt.datetime) -> dict[str, Any] | None:
    """当日且 QUOTE_STALE_S 内的 quote;否则 None(回落 EOD)。"""
    try:
        row = c.execute("SELECT price, prev_close, volume, quote_ts, fetched_ts FROM intraday_quotes WHERE symbol=?", (sym,)).fetchone()
    except sqlite3.OperationalError:
        # v2.4:api 容器可能在 worker 首拍建表前读库(docker cp 热更新/重建容器窗口)——缺表按"无 quote"回落 EOD,不抛
        return None
    if not row or row[0] is None:
        return None
    price, prev_close, volume, quote_ts, fetched_ts = row
    now_ts = int(now.timestamp())
    if now_ts - int(fetched_ts or 0) > QUOTE_STALE_S:
        return None
    qday = dt.datetime.fromtimestamp(int(quote_ts or fetched_ts), tz=ET).date()
    if qday != now.date():
        return None
    return {"price": float(price), "prev_close": float(prev_close) if prev_close else None,
            "volume": float(volume or 0), "quote_ts": int(quote_ts or fetched_ts)}


def _pull_from_date(c, sym: str, *, initial_days: int = INITIAL_BAR_DAYS) -> dt.date | None:
    latest = _latest_bar_date(c, sym)
    if latest is None:
        return None
    nxt = latest + dt.timedelta(days=1)
    end = _now_et().date()
    if nxt > end:
        return end  # 最新 bar 已是今日:重拉今日一行(盘中刷新/终盘补拉用),不是"不拉"
    return nxt


def _bar_limit_for_symbol(c, sym: str, requested: int) -> int:
    if _latest_bar_date(c, sym) is None:
        return max(requested, INITIAL_BAR_DAYS)
    return requested


def pull_daily_bars(
    c,
    symbols: list[str],
    *,
    limit: int = DAILY_BAR_LIMIT,
    skip_fresh: bool = True,
    deadline: float | None = None,
) -> int:
    """FMP premium 主源 → daily_bars;Alpaca 备份补 FMP 缺票(2026-08-17 Lyra 拍板)。

    skip_fresh: skip symbols whose latest bar already satisfies §0 fresh rule.
    deadline: unix ts; stop pulling when exceeded (partial OK).
    """
    key, secret = os.getenv("ALPACA_API_KEY", ""), os.getenv("ALPACA_SECRET_KEY", "")
    n = 0
    uniq = list(dict.fromkeys(symbols))
    if skip_fresh:
        reasons: dict[str, int] = {}
        kept: list[str] = []
        gap: list[str] = []
        for s in uniq:
            need, why = needs_pull(c, s)
            if need:
                kept.append(s)
                reasons[why] = reasons.get(why, 0) + 1
                if why in ("gap_cooldown", "rth_missing_today"):   # v2.1:盘中"无当日行"同样走断路器
                    gap.append(s)
        if reasons:
            log.info("pull_daily_bars: due=%d/%d reasons=%s", len(kept), len(uniq), reasons)
        # 断路器:大面积"缺上一收盘日 bar"(节假日/数据源未发布)——先探 GAP_PROBE_N 票,全空则整批记尝试
        # 进冷却、本拍不拉,把节假日夜的调用量从 N×(夜/冷却) 压到 GAP_PROBE_N×(夜/冷却)
        # 盘中若 FMP EOD 不回当日行(戌 8-25 盘前实测已是这样),断路器把每 30 分钟 1768 次探测压到 10 次;
        # 当日 movers 席在这种源下只能等收盘后终盘补拉,盘中想要同日 movers 得换 quote 类端点——那是另一件事
        # 触发线 = max(2×探测数, min(GAP_BREAKER_MIN, 本批票数)):整批都缺时哪怕批只有 150(分片)也触发;
        # 501 全表里零星 30 票缺(正常滞后)不触发
        if FMP_API_KEY and len(gap) >= max(2 * GAP_PROBE_N, min(GAP_BREAKER_MIN, len(uniq))):
            probe = gap[:GAP_PROBE_N]
            hit = 0
            for s in probe:
                bars = fetch_fmp_daily_bars(s, _bar_limit_for_symbol(c, s, limit), from_date=_pull_from_date(c, s))
                _log_attempt(c, s, got=bool(bars))
                if bars:
                    n += _store_daily_bars(c, s, bars)
                    hit += 1
            if hit == 0:
                for s in gap:
                    _log_attempt(c, s, got=False)
                _cool = RTH_REFRESH_S if _is_rth() else OFFHOURS_COOLDOWN_S
                _set_state(c, "gap_breaker", {"until": int(_now_et().timestamp()) + _cool,
                                              "n": len(gap), "rth": _is_rth(), "probe": len(probe)})
                log.info("pull_daily_bars: gap breaker — %d 票缺目标日 bar(%s),探 %d 全空,整批记尝试进冷却",
                         len(gap), "盘中" if _is_rth() else "盘外", len(probe))
                gs = set(gap)
                kept = [s for s in kept if s not in gs]
            else:
                ps = set(probe)
                kept = [s for s in kept if s not in ps]
        uniq = kept
    if not uniq:
        return 0
    start = (_now_et() - dt.timedelta(days=max(INITIAL_BAR_DAYS, limit + 5))).date().isoformat()

    # ---- FMP 主源(逐票;premium 300/min 速率充足)----
    if FMP_API_KEY:
        remaining: list[str] = []
        for idx, sym in enumerate(uniq):
            if deadline is not None and time.time() >= deadline:
                remaining.extend(uniq[idx:])
                break
            sym_limit = _bar_limit_for_symbol(c, sym, limit)
            from_date = _pull_from_date(c, sym)
            bars = fetch_fmp_daily_bars(sym, sym_limit, from_date=from_date)
            _log_attempt(c, sym, got=bool(bars))
            if bars:
                n += _store_daily_bars(c, sym, bars)
            else:
                remaining.append(sym)
        uniq = remaining

    # ---- Alpaca 备份(FMP 缺的票)----
    if not (key and secret and uniq):
        return n
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}

    def _store_batch(batch: list[str], bars_map: dict) -> None:
        nonlocal n
        for alpaca_sym, bars in bars_map.items():
            canonical = db.canonical_ticker(alpaca_sym, batch)
            n += _store_daily_bars(c, canonical, bars, src=BAR_SRC_IEX)
            _log_attempt(c, canonical, got=bool(bars))

    def _pull_one(cli: httpx.Client, sym: str) -> None:
        nonlocal n
        alpaca_sym = db.alpaca_ticker(sym)
        try:
            r1 = cli.get(
                "https://data.alpaca.markets/v2/stocks/bars",
                params=bars_params(
                    symbols=alpaca_sym,
                    timeframe="1Day",
                    start=start,
                    limit=limit,
                    feed="iex",
                ),
                headers=headers,
            )
            if r1.status_code == 429:
                time.sleep(1.2)
                r1 = cli.get(
                    "https://data.alpaca.markets/v2/stocks/bars",
                    params=bars_params(
                        symbols=alpaca_sym,
                        timeframe="1Day",
                        start=start,
                        limit=limit,
                        feed="iex",
                    ),
                    headers=headers,
                )
            r1.raise_for_status()
            bm = r1.json().get("bars") or {}
            bars = bm.get(alpaca_sym) or bm.get(sym) or (
                next(iter(bm.values())) if bm else []
            )
            _log_attempt(c, sym, got=bool(bars))
            if bars:
                n += _store_daily_bars(c, sym, bars, src=BAR_SRC_IEX)
        except Exception as exc1:
            _log_attempt(c, sym, got=False)
            log.debug("daily skip %s: %s", sym, exc1)

    try:
        with httpx.Client(timeout=60) as cli:
            for i in range(0, len(uniq), SP500_BATCH):
                if deadline is not None and time.time() >= deadline:
                    log.info("pull_daily_bars deadline hit · remaining=%d", len(uniq) - i)
                    break
                batch = uniq[i : i + SP500_BATCH]
                alpaca_syms = ",".join(db.alpaca_ticker(s) for s in batch)
                got: set[str] = set()
                try:
                    # 必须 sort=desc:Alpaca 默认升序,limit=2 会只拿到 start 附近最旧K线。
                    # IEX 多票请求常只回子集——缺的必须逐票补,否则 movers 停在旧日。
                    r = cli.get(
                        "https://data.alpaca.markets/v2/stocks/bars",
                        params=bars_params(
                            symbols=alpaca_syms,
                            timeframe="1Day",
                            start=start,
                            limit=limit,
                            feed="iex",
                        ),
                        headers=headers,
                    )
                    r.raise_for_status()
                    bars_map = r.json().get("bars") or {}
                    _store_batch(batch, bars_map)
                    for ak in bars_map:
                        got.add(db.canonical_ticker(ak, batch))
                        got.add(str(ak).upper().replace(".", "-"))
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code not in (400, 429):
                        raise
                for sym in batch:
                    if deadline is not None and time.time() >= deadline:
                        break
                    if sym not in got and db.alpaca_ticker(sym) not in got:
                        _pull_one(cli, sym)
    except Exception as exc:
        log.warning("pull_daily_bars: %s", exc)
    return n


def _daily_closes(c, sym: str, need: int) -> list[float]:
    rows = c.execute(
        "SELECT c FROM daily_bars WHERE symbol=? ORDER BY ts DESC LIMIT ?", (sym, need)
    ).fetchall()
    return [float(r[0]) for r in rows][::-1]


def _percentile_ranks(raw: dict[str, float]) -> dict[str, float]:
    if len(raw) < 2:
        return {s: 50.0 for s in raw}
    items = sorted((v, s) for s, v in raw.items())
    out: dict[str, float] = {}
    n = len(items)
    for i, (_, s) in enumerate(items):
        out[s] = round(100.0 * i / (n - 1), 1)
    return out


def compute_env_factor_truth(c, watchlist: list[str]) -> int:
    """MOM_20D / REV_5D / VOL_20D percentiles within env universe → factors table."""
    now = int(time.time())
    env = [s for s in watchlist if s not in db.SURFACE_DENY and not str(s).endswith("-USD")]
    raw_mom: dict[str, float] = {}
    raw_rev: dict[str, float] = {}
    raw_vol: dict[str, float] = {}
    ok = 0
    for sym in env:
        closes = _daily_closes(c, sym, 21)
        if len(closes) < 20:
            continue
        base_20 = closes[0]
        mom = (closes[-1] - base_20) / base_20 if base_20 else 0.0
        rev = -(closes[-1] - closes[-6]) / closes[-6] if len(closes) >= 6 and closes[-6] else 0.0
        rets = [(closes[i + 1] - closes[i]) / closes[i] for i in range(len(closes) - 1) if closes[i]]
        vol = statistics.pstdev(rets[-20:]) * math.sqrt(252) if len(rets) >= 2 else 0.0
        raw_mom[sym] = mom
        raw_rev[sym] = rev
        raw_vol[sym] = vol
        ok += 1
    pct_mom = _percentile_ranks(raw_mom)
    pct_rev = _percentile_ranks(raw_rev)
    pct_vol = _percentile_ranks(raw_vol)
    for sym in env:
        fac = {
            "mom_20d_pct": pct_mom.get(sym),
            "rev_5d_pct": pct_rev.get(sym),
            "vol_20d_pct": pct_vol.get(sym),
        }
        for name, val in fac.items():
            if val is None:
                continue
            c.execute(
                "INSERT OR REPLACE INTO factors(ts, symbol, name, value) VALUES(?,?,?,?)",
                (now, sym, name, float(val)),
            )
    if ok:
        db.set_health(c, "factor_truth", "ok", f"env pct · {ok}/{len(env)} syms · vs env")
    else:
        db.set_health(c, "factor_truth", "waiting", f"daily bars不足 · need ≥20d · env {len(env)}")
    return ok


def _adv20_dollar(c, sym: str) -> float | None:
    """20-day avg dollar volume (close×volume); excludes latest bar per SPEC.
    v2.5:只用综合量行(src 非 alpaca_iex;NULL=历史 FMP 行);综合量行不足 20 根 → None(无实测,地板不过)。"""
    try:
        rows = c.execute(
            "SELECT c, v FROM daily_bars WHERE symbol=? AND (src IS NULL OR src<>?) ORDER BY ts DESC LIMIT 21",
            (sym, BAR_SRC_IEX),
        ).fetchall()
    except sqlite3.OperationalError:
        # api 容器在 worker 做 ALTER 之前读库:旧表无 src 列,退回无来源过滤(历史行本就全是 FMP)
        rows = c.execute("SELECT c, v FROM daily_bars WHERE symbol=? ORDER BY ts DESC LIMIT 21", (sym,)).fetchall()
    if len(rows) < 21:
        return None
    vals = [float(r[0]) * float(r[1] or 0) for r in rows[1:21]]
    return sum(vals) / len(vals) if vals else None


def _movers_symbol_sets() -> tuple[list[str], set[str], set[str]]:
    sp500 = load_sp500_symbols()
    udoc = load_universe_market()
    market = [str(s).upper() for s in (udoc.get("symbols") or [])] if udoc else []
    sp_set = set(sp500)
    mkt_set = set(market)
    union = list(dict.fromkeys(sp500 + market))
    return union, sp_set, mkt_set


def _universe_market_only_sorted(udoc: dict[str, Any] | None, sp_set: set[str]) -> list[str]:
    if not udoc:
        return []
    rows = udoc.get("rows") or []
    out: list[str] = []
    seen: set[str] = set()
    for r in rows:
        sym = str(r.get("symbol") or "").upper()
        if not sym or sym in sp_set or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return out


def _universe_tag(sym: str, sp_set: set[str], mkt_set: set[str]) -> str:
    in_sp = sym in sp_set
    in_mkt = sym in mkt_set
    if in_sp and in_mkt:
        return "both"
    if in_sp:
        return "sp500"
    return "market"


def _movers_passes_floor(c, sym: str, last_c: float, adv: float | None = None) -> bool:
    if sym in ETF_DENY_MOVERS:
        return False
    if last_c < MOVERS_PRICE_MIN:
        return False
    if adv is None:
        adv = _adv20_dollar(c, sym)
    if adv is None or adv < MOVERS_ADV20_MIN:
        return False
    return True


def pull_sp500_and_universe_shard(
    c,
    *,
    sp500_limit: int = 2,
    univ_limit: int = INITIAL_BAR_DAYS,
    skip_fresh: bool = True,
    deadline: float | None = None,
) -> tuple[int, int]:
    """SP500 full pass first, then ≤UNIV_BARS_PER_TICK market symbols (dollar_vol desc)."""
    sp500 = load_sp500_symbols()
    n_sp = 0
    if sp500:
        n_sp = pull_daily_bars(c, sp500, limit=sp500_limit, skip_fresh=skip_fresh, deadline=deadline)
    udoc = load_universe_market()
    sp_set = set(sp500)
    univ = _universe_market_only_sorted(udoc, sp_set)
    n_univ = 0
    if not univ:
        return n_sp, n_univ
    st = _get_state(c, "univ_bars_cursor") or {"idx": 0}
    idx = int(st.get("idx", 0)) % len(univ)
    batch: list[str] = []
    scanned = 0
    while scanned < len(univ) and len(batch) < UNIV_BARS_PER_TICK:
        sym = univ[(idx + scanned) % len(univ)]
        scanned += 1
        if skip_fresh and not needs_pull(c, sym)[0]:
            continue
        batch.append(sym)
    if batch:
        n_univ = pull_daily_bars(c, batch, limit=univ_limit, skip_fresh=skip_fresh, deadline=deadline)
    new_idx = (idx + max(scanned, UNIV_BARS_PER_TICK)) % len(univ)
    _set_state(c, "univ_bars_cursor", {"idx": new_idx, "total": len(univ), "batch_n": len(batch)})
    return n_sp, n_univ


def _build_mover_rows(
    c,
    symbols: list[str],
    bfs_syms: set[str],
    sp_set: set[str],
    mkt_set: set[str],
    *,
    readonly: bool = False,
) -> dict[str, Any]:
    """Top gainers/losers by RET 1D; sp500 ∪ universe with price/adv20 floors."""
    now_dt = _now_et()
    now = int(now_dt.timestamp())
    rows: list[dict[str, Any]] = []
    last_closed = _last_closed_trading_day(now=now_dt)
    symbols = list(dict.fromkeys(symbols))     # 去重(调用方并集已去重;此处兜底,重复票不重复入榜)
    src_mix = {"quote": 0, "eod": 0}
    for sym in symbols:
        if sym in db.SURFACE_DENY:
            continue
        bars = c.execute(
            "SELECT ts, c, v FROM daily_bars WHERE symbol=? ORDER BY ts DESC LIMIT 2", (sym,)
        ).fetchall()
        if len(bars) < 2:
            continue
        q = _fresh_quote(c, sym, now_dt) if INTRADAY_QUOTES else None
        if q:
            # v2.2:盘中同日 movers 走 quote;prev 用 quote 的 previousClose(避开"最新 bar 是当日部分 bar"的坑),
            # 缺 previousClose 时用库内最近一根 非当日 bar 的收盘
            last_f = q["price"]
            prev_c = q["prev_close"]
            if not prev_c:
                for b in bars:
                    if dt.datetime.fromtimestamp(int(b[0]), tz=ET).date() < now_dt.date():
                        prev_c = float(b[1]); break
            if not prev_c:
                continue
            last_ts, vol, source = q["quote_ts"], q["volume"], "quote"
        else:
            last_ts, last_c, vol = bars[0]
            prev_c = float(bars[1][1])
            last_f, source = float(last_c), "eod"
        if not prev_c:
            continue
        adv20 = _adv20_dollar(c, sym)          # 一票一查(原:地板一查、行内再查)
        if not _movers_passes_floor(c, sym, last_f, adv20):
            continue
        ret1d = (last_f - prev_c) / prev_c * 100.0
        bar_day = dt.datetime.fromtimestamp(int(last_ts), tz=ET).date()
        bar_age_s = now - int(last_ts)
        stale = source == "eod" and bar_day < last_closed - dt.timedelta(days=4)
        src_mix[source] += 1
        rows.append({
            "sym": sym,
            "symbol": sym,
            "last": round(last_f, 4),
            "ret1d": round(ret1d, 2),
            "chg_pct": round(ret1d, 2),
            "volume": float(vol or 0),
            "adv20": round(adv20, 0) if adv20 is not None else None,
            "asof_ts": int(last_ts),
            "bfs": sym in bfs_syms,
            "universe": _universe_tag(sym, sp_set, mkt_set),
            "source": source,
            "stale": stale,
            "stale_reason": f"bar_age_{bar_age_s//3600}h" if stale else None,
        })
    if not rows:
        if not readonly:
            db.set_health(c, "daily_movers", "empty", "无 movers daily bars")
        return {
            "items": [], "gainers": [], "losers": [], "asof_et": None, "computed_ts": now,
            "status": "empty", "universe": len(symbols), "with_data": 0,
        }

    rows.sort(key=lambda r: r["ret1d"], reverse=True)
    gainers = rows[:MOVERS_TOP]
    losers = list(reversed(rows[-MOVERS_TOP:])) if len(rows) >= MOVERS_TOP else list(reversed(rows))
    asof_ts = max(r["asof_ts"] for r in rows)
    asof_et = dt.datetime.fromtimestamp(asof_ts, tz=ET).strftime("%H:%M:%S")
    payload = {
        "gainers": gainers,
        "losers": losers,
        "asof_et": asof_et,
        "asof_ts": asof_ts,
        "computed_ts": now,
        "universe": len(symbols),
        "with_data": len(rows),
        "source_mix": src_mix,
        "status": "ok",
    }
    if not readonly:
        db.set_health(
            c, "daily_movers", "ok",
            json.dumps({"gainers": len(gainers), "losers": len(losers), "asof_et": asof_et})[:400],
        )
    return payload


def compute_sp500_movers(c, sp500: list[str], bfs_syms: set[str], *, readonly: bool = False) -> dict[str, Any]:
    union, sp_set, mkt_set = _movers_symbol_sets()
    if not union:
        union = list(sp500)
        sp_set = set(sp500)
        mkt_set = set()
    return _build_mover_rows(c, union, bfs_syms, sp_set, mkt_set, readonly=readonly)


def load_movers_cache(c) -> dict[str, Any]:
    row = c.execute("SELECT ts, status, detail FROM health WHERE component='daily_movers'").fetchone()
    if not row:
        return {"items": [], "asof_et": None, "status": "waiting"}
    ts, status, detail = row
    # Full payload rebuilt from daily_bars on read if we stored minimal detail
    sp500 = load_sp500_symbols()
    bfs = set(db.bfs_candidate_symbols())
    if status == "ok" and sp500:
        full = compute_sp500_movers_readonly(c, sp500, bfs)
        full["cache_age_s"] = int(time.time()) - int(ts)
        full["status"] = status
        return full
    return {"items": [], "asof_et": None, "status": status, "detail": detail}


def compute_sp500_movers_readonly(c, sp500: list[str], bfs_syms: set[str]) -> dict[str, Any]:
    """Read movers without writing health (for API). A5: actually read-only now."""
    return compute_sp500_movers(c, sp500, bfs_syms, readonly=True)


def movers_for_api(c, *, direction: str = "up") -> dict[str, Any]:
    sp500 = load_sp500_symbols()
    bfs = set(db.bfs_candidate_symbols())
    if not sp500:
        return {"items": [], "asof_et": None, "status": "no_universe", "direction": direction}
    payload = _movers_from_daily_bars(c, sp500, bfs)
    items = payload.get("gainers") if direction != "down" else payload.get("losers")
    return {
        "items": items or [],
        "asof_et": payload.get("asof_et"),
        "asof_ts": payload.get("asof_ts"),
        "computed_ts": payload.get("computed_ts"),
        "status": payload.get("status", "ok"),
        "direction": direction,
        "universe": payload.get("universe"),
        "with_data": payload.get("with_data"),
    }


def _movers_from_daily_bars(c, sp500: list[str], bfs_syms: set[str]) -> dict[str, Any]:
    union, sp_set, mkt_set = _movers_symbol_sets()
    if not union:
        union = list(sp500)
        sp_set = set(sp500)
        mkt_set = set()
    return _build_mover_rows(c, union, bfs_syms, sp_set, mkt_set, readonly=True)


def run_factor_truth_cycle(c, watchlist: list[str], *, budget_s: float | None = None) -> None:
    """One worker tick: env daily bars + env percentiles + sp500/universe movers."""
    ensure_schema(c)
    t0 = time.time()
    deadline = (t0 + budget_s) if budget_s and budget_s > 0 else None
    env = [s for s in watchlist if not str(s).endswith("-USD")]
    n_env = pull_daily_bars(c, env, limit=DAILY_BAR_LIMIT, skip_fresh=True, deadline=deadline)
    for sym in env:
        cnt = c.execute("SELECT COUNT(*) FROM daily_bars WHERE symbol=?", (sym,)).fetchone()[0]
        if cnt < 20:
            n_env += pull_daily_bars(
                c, [sym], limit=DAILY_BAR_LIMIT, skip_fresh=False, deadline=deadline
            )
    compute_env_factor_truth(c, env)
    sp500 = load_sp500_symbols()
    if sp500:
        n_sp, n_univ = pull_sp500_and_universe_shard(
            c, sp500_limit=2, univ_limit=INITIAL_BAR_DAYS, skip_fresh=True, deadline=deadline
        )
        union_syms, _sp_set, _mkt_set = _movers_symbol_sets()
        n_q = refresh_intraday_quotes(c, union_syms or list(sp500), deadline=deadline)   # v2.2:盘中 quote 轮刷
        _persist_fmp_get_count(c)
        bfs = set(db.bfs_candidate_symbols())
        _t_movers = time.time()
        payload = _movers_from_daily_bars(c, sp500, bfs)
        _movers_ms = int((time.time() - _t_movers) * 1000)
        union_n = payload.get("universe", len(sp500))
        log.info(
            "factor_truth: movers_scan union=%d with_data=%d elapsed=%dms",
            union_n, payload.get("with_data", 0), _movers_ms,
        )
        for side in ("gainers", "losers"):
            for row in payload.get(side) or []:
                row.setdefault("symbol", row.get("sym"))
                row.setdefault("chg_pct", row.get("ret1d"))
        db.set_health(
            c,
            "daily_movers",
            payload.get("status", "ok"),
            json.dumps({
                "gainers": len(payload.get("gainers") or []),
                "losers": len(payload.get("losers") or []),
                "asof_et": payload.get("asof_et"),
                "with_data": payload.get("with_data"),
                "bars_pulled_sp500": n_sp,
                "bars_pulled_univ": n_univ,
                "quotes_refreshed": n_q,
                "source_mix": payload.get("source_mix"),
                "fmp_gets": fmp_get_count_today(),
                "elapsed_s": int(time.time() - t0),
            }, ensure_ascii=False)[:400],
        )
        log.info(
            "factor_truth: env_daily=%d sp500_daily=%d univ_daily=%d quotes=%d movers=%d src=%s fmp_gets=%d elapsed=%ss",
            n_env, n_sp, n_univ, n_q, payload.get("with_data", 0), payload.get("source_mix"), fmp_get_count_today(), int(time.time() - t0),
        )
