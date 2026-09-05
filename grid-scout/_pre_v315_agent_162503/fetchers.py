"""fetchers.py —— 晚报确定性采集层(零 LLM,零爬虫,全官方/公开源)。
每源:try/except → {source, ok, ts, items[]};失败如实入记录,不静默。
铁则:FRED 需免费 API key(可选源,缺 key 自动跳过并如实记录);
     其余源零注册。守恒手写 v1 + 本机 ssl/FRED回退/Alpaca;v3.13 交易日 ET 锚定。"""
from __future__ import annotations
import datetime, json, os, re, ssl, urllib.request
try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:
    _ET = None


def trading_date():
    """美股交易日期(ET 定义,减 4 小时使 ET 0-4 点仍归前一交易日——
    21:00 PST 晚班 = 00:00 ET 不跨日)。机器时区无关。v3.12/v3.13。"""
    if _ET is None:
        print("[fetchers] ZoneInfo 不可用——回退本机日期(仅 PST 机器安全)")
        return datetime.date.today()
    return (datetime.datetime.now(_ET) - datetime.timedelta(hours=4)).date()


def prev_trading_day(d):
    """上一交易日(跳周末:周一→上周五)。节假日未处理——已知边界。"""
    d = d - datetime.timedelta(days=1)
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d


def et_now_hm():
    """当前 ET 钟点 HH:MM(prompt/渲染共用,杜绝硬编码 9:45)。v3.13。"""
    if _ET is None:
        return datetime.datetime.now().strftime("%H:%M") + "(本机时区,ZoneInfo 不可用)"
    return datetime.datetime.now(_ET).strftime("%H:%M")


UA = {"User-Agent": "grid-evening-scout/1.0 (research; contact: local)"}
SKIPS: list = []          # 本轮逐条跳过记录,与 raw 同文件落盘(侯三审:不许静默吞)
LIQ_MCAP_FLOOR_B = float(os.getenv("LIQ_MCAP_FLOOR_B", "2.0"))


def _log_skip(source, item, reason):
    SKIPS.append({"source": source, "item": str(item)[:80], "reason": str(reason)[:200],
                  "ts": datetime.datetime.now().astimezone().isoformat()})
TIMEOUT = 20


def _ssl_context():
    """本机 Python 常见缺 CA → CERTIFICATE_VERIFY_FAILED;优先 certifi。"""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _get(url, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_context()) as r:
        return r.read().decode("utf-8", "replace")


def _wrap(source, fn):
    ts = datetime.datetime.now().astimezone().isoformat()
    n_skips_before = len(SKIPS)
    try:
        items = fn()
        n_sk = sum(1 for k in SKIPS[n_skips_before:] if k["source"] == source)
        if not items and n_sk > 0:
            # 沙箱判例(2026-07-29):全条目被跳=源级失败,不许 ok+空列表装"今天没数据"
            return {"source": source, "ok": False, "ts": ts,
                    "error": "all %d items skipped, see skips" % n_sk, "items": []}
        return {"source": source, "ok": True, "ts": ts, "items": items[:40]}
    except Exception as e:
        return {"source": source, "ok": False, "ts": ts, "error": str(e)[:300], "items": []}


def fetch_treasury_yields():
    """财政部日收益率曲线(官方,无 key)。"""
    def go():
        y = datetime.date.today().year
        url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
               f"daily-treasury-rates.csv/{y}/all?type=daily_treasury_yield_curve&_format=csv")
        rows = _get(url).strip().splitlines()
        head = rows[0].split(","); last = rows[1].split(",")
        return [{"field": h, "value": v} for h, v in zip(head, last)]
    return _wrap("treasury_yields", go)


def _fred_via_api(key: str) -> list:
    out = []
    for sid in ("UNRATE", "FEDFUNDS", "CPIAUCSL"):
        u = ("https://api.stlouisfed.org/fred/series/observations?series_id=%s"
             "&api_key=%s&file_type=json&sort_order=desc&limit=2" % (sid, key))
        obs = json.loads(_get(u))["observations"]
        out.append({"series": sid, "latest": obs[0], "prev": obs[1] if len(obs) > 1 else None,
                    "via": "fred_api"})
    return out


def _macro_via_bls_nyfed() -> list:
    """零 key 回退:BLS 失业率/CPI + NY Fed EFFR/SOFR(利率代理,非 FRED FEDFUNDS 本体)。"""
    out = []
    body = json.dumps({
        "seriesid": ["LNS14000000", "CUSR0000SA0"],
        "startyear": str(datetime.date.today().year - 1),
        "endyear": str(datetime.date.today().year),
    }).encode()
    req = urllib.request.Request(
        "https://api.bls.gov/publicAPI/v2/timeseries/data/",
        data=body,
        headers={**UA, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_context()) as r:
        payload = json.loads(r.read().decode("utf-8", "replace"))
    if payload.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError("BLS status=%s" % payload.get("status"))
    alias = {"LNS14000000": "UNRATE", "CUSR0000SA0": "CPIAUCSL"}
    for s in (payload.get("Results") or {}).get("series") or []:
        sid = alias.get(s.get("seriesID"), s.get("seriesID"))
        rows = s.get("data") or []
        if not rows:
            _log_skip("fred_macro", sid, "BLS empty"); continue
        latest, prev = rows[0], (rows[1] if len(rows) > 1 else None)
        out.append({
            "series": sid,
            "latest": {"date": "%s-%s" % (latest.get("year"), latest.get("period")),
                       "value": latest.get("value"), "periodName": latest.get("periodName")},
            "prev": ({"date": "%s-%s" % (prev.get("year"), prev.get("period")),
                      "value": prev.get("value")} if prev else None),
            "via": "bls_public",
        })
    # 利率:NY Fed EFFR(优先) / SOFR
    try:
        j = json.loads(_get("https://markets.newyorkfed.org/api/rates/all/latest.json",
                            headers={"Accept": "application/json"}))
        rates = j.get("refRates") or []
        effr = next((x for x in rates if x.get("type") == "EFFR"), None)
        sofr = next((x for x in rates if x.get("type") == "SOFR"), None)
        pick = effr or sofr
        if pick and pick.get("percentRate") is not None:
            out.append({
                "series": "FEDFUNDS" if effr else "SOFR",
                "latest": {"date": pick.get("effectiveDate"),
                           "value": str(pick.get("percentRate"))},
                "prev": None,
                "via": "nyfed",
                "note": "EFFR/SOFR 代理联邦基金读数(非 FRED FEDFUNDS 月频系列)",
            })
        else:
            _log_skip("fred_macro", "EFFR/SOFR", "nyfed missing percentRate")
    except Exception as e:
        _log_skip("fred_macro", "nyfed", e)
    if not out:
        raise RuntimeError("BLS/NYFed macro empty")
    return out


def fetch_fred():
    """宏观三件套:优先 FRED API key;缺 key 或失败 → BLS+NY Fed 零 key 回退。"""
    key = os.getenv("FRED_API_KEY", "").strip()
    def go():
        if key:
            try:
                return _fred_via_api(key)
            except Exception as e:
                _log_skip("fred_macro", "fred_api", e)
        return _macro_via_bls_nyfed()
    return _wrap("fred_macro", go)


def fetch_edgar_recent():
    """EDGAR 全文检索:近两日 8-K/425(并购信号高发表格)。官方,需 UA。
    v3.13:检索窗随 trading_date 锚定(时间语义家族收尾)。"""
    def go():
        base = trading_date()
        frm = (base - datetime.timedelta(days=2)).isoformat()
        u = ("https://efts.sec.gov/LATEST/search-index?q=%22merger%20agreement%22&forms=8-K"
             f"&startdt={frm}&enddt={base.isoformat()}")
        data = json.loads(_get(u))
        hits = data.get("hits", {}).get("hits", [])
        return [{"company": h["_source"].get("display_names", ["?"])[0],
                 "form": h["_source"].get("file_type"), "filed": h["_source"].get("file_date")}
                for h in hits]
    return _wrap("edgar_ma_8k", go)


def fetch_fda_press():
    """FDA 新闻 RSS(批准/announce 高发)。官方,无 key。"""
    def go():
        xml = _get("https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml")
        items = []
        for chunk in xml.split("<item>")[1:]:
            t = chunk.split("<title>")[1].split("</title>")[0] if "<title>" in chunk else "?"
            d = chunk.split("<pubDate>")[1].split("</pubDate>")[0] if "<pubDate>" in chunk else ""
            items.append({"title": t.strip()[:200], "date": d.strip()})
        return items
    return _wrap("fda_press", go)


def fetch_commodities():
    """油(WTI)金(XAU)日线 via stooq 日线 CSV 下载端点(侯三审换新 URL,取末行)。"""
    def go():
        out = []
        for sym, name in (("cl.f", "WTI"), ("xauusd", "GOLD")):
            try:
                rows = _get(f"https://stooq.com/q/d/l/?s={sym}&i=d").strip().splitlines()
                if len(rows) >= 2:
                    head, last = rows[0].split(","), rows[-1].split(",")
                    out.append({"name": name, **dict(zip(head, last))})
                else:
                    _log_skip("commodities", sym, "empty csv")
            except Exception as e:
                _log_skip("commodities", sym, e)
        return out
    return _wrap("commodities", go)





def _load_alpaca_keys():
    """优先进程环境;否则从本仓已有 .env 读(不打印值)。"""
    key = os.getenv("ALPACA_API_KEY", "").strip()
    sec = os.getenv("ALPACA_SECRET_KEY", "").strip()
    if key and sec:
        return key, sec
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, ".env"),
        os.path.join(here, "..", "aether_nexus", ".env"),
        os.path.join(here, "..", "alpha-platform", ".env"),
    ]
    found = {}
    for path in candidates:
        try:
            with open(path, encoding="utf-8") as f:
                for ln in f:
                    s = ln.strip()
                    if not s or s.startswith("#") or "=" not in s:
                        continue
                    k, _, v = s.partition("=")
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY") and v and k not in found:
                        found[k] = v
        except OSError:
            continue
        if found.get("ALPACA_API_KEY") and found.get("ALPACA_SECRET_KEY"):
            break
    return found.get("ALPACA_API_KEY", ""), found.get("ALPACA_SECRET_KEY", "")


def _indices_from_alpaca():
    """本机已有 Alpaca key。免费 IEX 无指数合约 → 用 ETF 代理:
    SPY≈SP500 环境, QQQ≈Nasdaq 环境, VIXY≈波动率(非 CBOE VIX 本身,须标注)。"""
    key, sec = _load_alpaca_keys()
    if not (key and sec):
        _log_skip("indices", "alpaca", "ALPACA_API_KEY/SECRET 未配置")
        return []
    feed = os.getenv("ALPACA_DATA_FEED", "iex").strip() or "iex"
    # name → (alpaca symbol, proxy note)
    plan = (
        ("SP500", "SPY", "SPY ETF proxy for SP500 env"),
        ("NASDAQ", "QQQ", "QQQ ETF proxy for Nasdaq env"),
        ("VIX", "VIXY", "VIXY ETF proxy — not CBOE VIX spot"),
    )
    syms = ",".join(p[1] for p in plan)
    url = ("https://data.alpaca.markets/v2/stocks/snapshots?symbols=" + syms)
    req = urllib.request.Request(
        url,
        headers={
            **UA,
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": sec,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_context()) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        _log_skip("indices", "alpaca", e)
        return []
    out = []
    for name, sym, note in plan:
        snap = data.get(sym) or {}
        bar = snap.get("dailyBar") or snap.get("prevDailyBar") or {}
        close = bar.get("c")
        ts = bar.get("t") or ""
        if close is None:
            _log_skip("indices", sym, "alpaca snapshot no close")
            continue
        day = str(ts)[:10]
        o = bar.get("o"); h = bar.get("h"); l = bar.get("l")
        prev_bar = snap.get("prevDailyBar") or {}
        pc = prev_bar.get("c")
        item = {
            "name": name,
            "Date": day,
            "Close": str(round(float(close), 4)),
            "close": float(close),
            "source": "alpaca",
            "proxy": sym,
            "feed": feed,
            "note": note,
        }
        try:
            if o is not None and h is not None and l is not None:
                o, h, l, c = float(o), float(h), float(l), float(close)
                item.update({"open": o, "high": h, "low": l})
                pc_f = float(pc) if pc is not None else None
                cl, chg, tape = _tape_from_ohlc(o, h, l, c, pc_f)
                item["close_loc"] = cl
                item["chg_pct"] = chg
                item["tape_flag"] = tape or ""
            else:
                item["tape_flag"] = ""
                item["close_loc"] = None
                item["chg_pct"] = None
        except (TypeError, ValueError):
            item.setdefault("tape_flag", "")
        out.append(item)
    return out


def _indices_from_yahoo():
    """Alpaca/stooq 都失败时的零 key 回退(真指数 close)。"""
    out = []
    for ysym, name in (("%5EGSPC", "SP500"), ("%5EIXIC", "NASDAQ"), ("%5EVIX", "VIX")):
        try:
            u = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
                 "?interval=1d&range=5d" % ysym)
            data = json.loads(_get(u, headers={"User-Agent": "Mozilla/5.0"}))
            res = (data.get("chart") or {}).get("result") or []
            if not res:
                _log_skip("indices", ysym, "yahoo empty result"); continue
            r0 = res[0]
            ts = (r0.get("timestamp") or [None])[-1]
            closes = ((r0.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
            close = next((c for c in reversed(closes) if c is not None), None)
            if close is None:
                _log_skip("indices", ysym, "yahoo no close"); continue
            day = (datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).date().isoformat()
                   if ts else "")
            out.append({"name": name, "Date": day, "Close": str(round(float(close), 4)),
                        "source": "yahoo-chart", "proxy": name})
        except Exception as e:
            _log_skip("indices", ysym, e)
    return out


def fetch_indices():
    """大盘/波动率环境读数。优先 Alpaca(SPY/QQQ/VIXY 代理)→ Yahoo 真指数 → stooq。
    Alpaca 免费层无 ^SPX/^VIX 合约,故用 ETF 代理并在 item.proxy/note 标明。"""
    def go():
        out = _indices_from_alpaca()
        if len(out) >= 3:
            return out
        have = {x["name"] for x in out}
        for it in _indices_from_yahoo():
            if it["name"] not in have:
                out.append(it)
                have.add(it["name"])
        if len(out) >= 3:
            return out
        for sym, name in (("^spx", "SP500"), ("^ndq", "NASDAQ"), ("^vix", "VIX")):
            if name in have:
                continue
            try:
                rows = _get(f"https://stooq.com/q/d/l/?s={sym}&i=d").strip().splitlines()
                if len(rows) >= 2 and not rows[0].lstrip().lower().startswith("<!"):
                    head, last = rows[0].split(","), rows[-1].split(",")
                    out.append({"name": name, **dict(zip(head, last)), "source": "stooq"})
                    have.add(name)
                else:
                    _log_skip("indices", sym, "empty csv or html block")
            except Exception as e:
                _log_skip("indices", sym, e)
        return out
    return _wrap("indices", go)



def _row_get(d, *keys):
    lower = {str(k).lower(): v for k, v in d.items()}
    for k in keys:
        if k.lower() in lower:
            return lower[k.lower()]
    return None


def _tape_from_ohlc(o, h, l, c, pc):
    close_loc = round((c - l) / (h - l), 2) if h > l else None
    chg_pct = round((c / pc - 1) * 100, 2) if pc else None
    tape = ""
    if pc is not None and close_loc is not None:
        tape = ("冲高回落" if (h > pc and close_loc < 0.4)
                else ("强势收高" if close_loc > 0.8 and c > pc else ""))
    return close_loc, chg_pct, tape


def _rsi14(closes):
    """Wilder RSI14(确定性;<15 根返回 None)。时机过滤器,非方向信号。v3.8。"""
    if len(closes) < 15:
        return None
    gains = losses = 0.0
    for i in range(1, 15):
        ch = closes[i] - closes[i - 1]
        gains += max(ch, 0.0)
        losses += max(-ch, 0.0)
    ag, al = gains / 14, losses / 14
    for i in range(15, len(closes)):
        ch = closes[i] - closes[i - 1]
        ag = (ag * 13 + max(ch, 0.0)) / 14
        al = (al * 13 + max(-ch, 0.0)) / 14
    if al == 0:
        return 100.0
    return round(100 - 100 / (1 + ag / al), 1)


def _stooq_daily(sym, name, skip_src):
    """stooq 日线末两行 → OHLC + close_loc/tape_flag + rsi14(v3.8)。"""
    try:
        rows = _get(f"https://stooq.com/q/d/l/?s={sym}&i=d").strip().splitlines()
        if len(rows) < 3 or rows[0].lstrip().lower().startswith("<!"):
            _log_skip(skip_src, sym, "csv too short or html")
            return None
        head = rows[0].split(",")
        prev = dict(zip(head, rows[-2].split(",")))
        last = dict(zip(head, rows[-1].split(",")))
        o = float(_row_get(last, "Open", "open"))
        h = float(_row_get(last, "High", "high"))
        l = float(_row_get(last, "Low", "low"))
        c = float(_row_get(last, "Close", "close"))
        pc = float(_row_get(prev, "Close", "close"))
        close_loc, chg_pct, tape = _tape_from_ohlc(o, h, l, c, pc)
        day = _row_get(last, "Date", "date")
        ci = next((i for i, k in enumerate(head) if str(k).lower() == "close"), None)
        closes = []
        if ci is not None:
            for r in (rows[-61:][1:] if len(rows) <= 61 else rows[-60:]):
                try:
                    closes.append(float(r.split(",")[ci]))
                except (ValueError, IndexError):
                    pass
        ticker = name if name in ("GLD", "SLV", "OXY", "USO") else (sym.split(".")[0].upper() if sym else name)
        return {"ticker": ticker, "name": name, "date": day, "Date": day, "open": o, "high": h, "low": l,
                "close": c, "Close": str(c), "chg_pct": chg_pct, "close_loc": close_loc,
                "rsi14": _rsi14(closes), "tape_flag": tape, "source": "stooq"}
    except Exception as e:
        _log_skip(skip_src, sym, e)
        return None


# v3.6 累加:对冲腿 + 资金迁徙目的地(cls=hedge|rotation)
_HEDGE_PLAN = (
    ("GLD", "GLD", "hedge"), ("SLV", "SLV", "hedge"),
    ("OXY", "OXY", "hedge"), ("USO", "USO", "hedge"),
    ("TLT", "TLT", "hedge"), ("UUP", "UUP", "hedge"),
    ("FXI", "FXI", "rotation"), ("KWEB", "KWEB", "rotation"),
    ("EWZ", "EWZ", "rotation"), ("EWJ", "EWJ", "rotation"),
    ("EEM", "EEM", "rotation"), ("BABA", "BABA", "rotation"),
)
_HEDGE_STOOQ = (
    ("gld.us", "GLD", "hedge"), ("slv.us", "SLV", "hedge"),
    ("oxy.us", "OXY", "hedge"), ("uso.us", "USO", "hedge"),
    ("tlt.us", "TLT", "hedge"), ("uup.us", "UUP", "hedge"),
    ("fxi.us", "FXI", "rotation"), ("kweb.us", "KWEB", "rotation"),
    ("ewz.us", "EWZ", "rotation"), ("ewj.us", "EWJ", "rotation"),
    ("eem.us", "EEM", "rotation"), ("baba.us", "BABA", "rotation"),
)


def alpaca_snapshots(symbols):
    """批量 Alpaca 快照 → {SYM: tape dict}。stooq 被墙时的本机主路径(sectors/movers)。"""
    key, sec = _load_alpaca_keys()
    syms = [str(s).upper() for s in (symbols or []) if s]
    if not (key and sec) or not syms:
        return {}
    out = {}
    for i in range(0, len(syms), 40):
        chunk = syms[i:i + 40]
        url = ("https://data.alpaca.markets/v2/stocks/snapshots?symbols="
               + ",".join(chunk))
        req = urllib.request.Request(
            url,
            headers={**UA, "APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec},
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_context()) as r:
                data = json.loads(r.read().decode())
        except Exception as e:
            _log_skip("alpaca_snapshots", ",".join(chunk[:3]), e)
            continue
        for sym in chunk:
            snap = data.get(sym) or {}
            bar = snap.get("dailyBar") or snap.get("prevDailyBar") or {}
            prev = snap.get("prevDailyBar") or {}
            try:
                o, h, l, c = float(bar["o"]), float(bar["h"]), float(bar["l"]), float(bar["c"])
                pc = float(prev["c"]) if prev.get("c") is not None else None
            except (KeyError, TypeError, ValueError):
                continue
            close_loc, chg_pct, tape = _tape_from_ohlc(o, h, l, c, pc)
            day = str(bar.get("t") or "")[:10]
            out[sym] = {
                "ticker": sym, "name": sym, "date": day, "Date": day,
                "open": o, "high": h, "low": l, "close": c, "Close": str(round(c, 4)),
                "chg_pct": chg_pct, "close_loc": close_loc, "tape_flag": tape or "",
                "rsi14": None, "source": "alpaca", "proxy": sym,
            }
    return out


def _hedge_from_alpaca():
    """对冲+迁徙腿优先 Alpaca 快照;附 close_loc/tape_flag/cls。"""
    snaps = alpaca_snapshots([p[0] for p in _HEDGE_PLAN])
    if not snaps:
        return []
    out = []
    for sym, name, cls in _HEDGE_PLAN:
        it = snaps.get(sym)
        if not it:
            _log_skip("hedge_assets", sym, "alpaca missing")
            continue
        d = dict(it)
        d["name"] = name
        d["cls"] = cls
        out.append(d)
    return out


def fetch_hedge_assets():
    """爬虫#8:对冲+迁徙资产——Alpaca 优先,stooq 回退。v3.4 对冲 ∪ v3.6 迁徙(累加)。"""
    def go():
        out = _hedge_from_alpaca()
        have = {x["name"] for x in out}
        # 缺腿或不足核心 4 只对冲 → stooq 补全(含 rotation cls)
        need_stooq = len([x for x in out if x.get("cls") == "hedge"]) < 4 or len(out) < len(_HEDGE_PLAN)
        if need_stooq:
            for sym, name, cls in _HEDGE_STOOQ:
                if name in have:
                    continue
                it = _stooq_daily(sym, name, "hedge_assets")
                if it:
                    it["cls"] = cls
                    out.append(it)
                    have.add(name)
        return out
    return _wrap("hedge_assets", go)


def fetch_earnings_calendar():
    """爬虫#10:Nasdaq 财报日历——上一交易日+今起5日(v3.11/v3.12:含昨日AMC)。"""
    def go():
        out = []
        base = trading_date()
        days = [prev_trading_day(base)] + [base + datetime.timedelta(days=k) for k in range(5)]
        for day_d in days:
            day = day_d.isoformat()
            try:
                raw = json.loads(_get(
                    "https://api.nasdaq.com/api/calendar/earnings?date=" + day,
                    {"Accept": "application/json"},
                ))
                rows = (((raw or {}).get("data") or {}).get("rows")) or []
                def cap(r):
                    ds = "".join(ch for ch in (r.get("marketCap") or "") if ch.isdigit())
                    return int(ds) if ds else 0
                # 前15会砍掉 TEAM(~$28B)等中盘今日AMC——与安装包对齐取前40
                for r in sorted(rows, key=cap, reverse=True)[:40]:
                    out.append({
                        "symbol": r.get("symbol"),
                        "name": (r.get("name") or "")[:40],
                        "date": day,
                        "when": r.get("time"),
                        "marketCap": r.get("marketCap"),
                    })
            except Exception as e:
                _log_skip("earnings_calendar", day, e)
        return out
    return _wrap("earnings_calendar", go)


def _parse_money(txt):
    t = (txt or "").replace(",", "").replace("$", "").strip()
    mult = 1.0
    if t[-1:].upper() in ("T", "B", "M", "K"):
        mult = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}[t[-1].upper()]
        t = t[:-1]
    try:
        return float(t) * mult
    except ValueError:
        return None


def fetch_ticker_liquidity(symbols):
    """爬虫#11(按需):Nasdaq summary 查市值/日均量——流动性闸的牙。不进夜间轮询。"""
    def go():
        out = []
        for sym in symbols:
            item = None
            for ac in ("stocks", "etf"):
                try:
                    raw = json.loads(_get(
                        "https://api.nasdaq.com/api/quote/%s/summary?assetclass=%s" % (sym, ac),
                        {"Accept": "application/json"},
                    ))
                    sd = ((raw or {}).get("data") or {}).get("summaryData") or {}
                    mc = _parse_money((sd.get("MarketCap") or {}).get("value"))
                    av = _parse_money((sd.get("AverageVolume") or {}).get("value"))
                    if mc or av:
                        item = {
                            "symbol": sym, "assetclass": ac,
                            "mcap_b": round(mc / 1e9, 2) if mc else None,
                            "avg_vol": int(av) if av else None,
                        }
                        break
                except Exception:
                    continue
            if item:
                out.append(item)
            else:
                _log_skip("liquidity_gate", sym, "no data in stocks/etf assetclass")
        return out
    return _wrap("liquidity_gate", go)


def fetch_sectors():
    """爬虫#12:板块 tape(SPDR 11 + SMH)——Alpaca 优先,stooq 回退。"""
    def go():
        plan = [
            ("XLK", "XLK科技"), ("XLC", "XLC通信"), ("XLY", "XLY可选消费"),
            ("XLP", "XLP必选消费"), ("XLE", "XLE能源"), ("XLF", "XLF金融"),
            ("XLV", "XLV医疗"), ("XLI", "XLI工业"), ("XLB", "XLB材料"),
            ("XLRE", "XLRE地产"), ("XLU", "XLU公用"), ("SMH", "SMH半导体"),
        ]
        snaps = alpaca_snapshots([p[0] for p in plan])
        out = []
        for sym, name in plan:
            it = snaps.get(sym)
            if it:
                d = dict(it)
                d["name"] = name
                out.append(d)
                continue
            st = _stooq_daily(sym.lower() + ".us", name, "sectors")
            if st:
                out.append(st)
            else:
                _log_skip("sectors", sym, "alpaca+stooq miss")
        return out
    return _wrap("sectors", go)


def fetch_fear_greed():
    """爬虫#9:CNN Fear & Greed(零 key)。dataviz JSON 优先;418/墙则刮 edition 页。"""
    def go():
        browser = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://edition.cnn.com",
            "Referer": "https://edition.cnn.com/markets/fear-and-greed",
        }
        # 1) 官方 dataviz
        try:
            data = json.loads(_get(
                "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                headers=browser,
            ))
            fg = data.get("fear_and_greed") or {}
            if fg and fg.get("score") is not None:
                return [{"score": fg.get("score"), "rating": fg.get("rating"),
                         "prev_close": fg.get("previous_close"),
                         "prev_1w": fg.get("previous_1_week"),
                         "prev_1m": fg.get("previous_1_month"),
                         "source": "cnn-dataviz"}]
            _log_skip("fear_greed", "graphdata", "empty fear_and_greed")
        except Exception as e:
            _log_skip("fear_greed", "graphdata", e)
        # 2) 刮 CNN 页内嵌 JSON / 文案
        try:
            html = _get(
                "https://edition.cnn.com/markets/fear-and-greed",
                headers={**browser, "Accept": "text/html,application/xhtml+xml"},
            )
            m = re.search(
                r'"fear_and_greed"\s*:\s*\{[^}]*"score"\s*:\s*([0-9.]+)[^}]*"rating"\s*:\s*"([^"]+)"',
                html,
            )
            if not m:
                m = re.search(
                    r'"score"\s*:\s*([0-9.]+)\s*,\s*"rating"\s*:\s*"(Extreme Greed|Greed|Neutral|Fear|Extreme Fear)"',
                    html,
                    re.I,
                )
            if m:
                return [{"score": float(m.group(1)), "rating": m.group(2),
                         "source": "cnn-html"}]
            # 可见文案: Fear & Greed Index is XX
            m2 = re.search(
                r"Fear\s*(?:&|&amp;)\s*Greed(?:\s*Index)?[^0-9]{0,40}([0-9]{1,3})",
                html,
                re.I,
            )
            if m2:
                score = int(m2.group(1))
                rating = (
                    "Extreme Greed" if score >= 75 else
                    "Greed" if score >= 55 else
                    "Neutral" if score >= 45 else
                    "Fear" if score >= 25 else "Extreme Fear"
                )
                return [{"score": score, "rating": rating, "source": "cnn-html-text"}]
            _log_skip("fear_greed", "cnn-html", "no score pattern")
        except Exception as e:
            _log_skip("fear_greed", "cnn-html", e)
        return []
    return _wrap("fear_greed", go)



def fetch_polymarket():
    """Polymarket 事件赔率。宏观/地缘事件桶全收;非事件只留头部热度。"""
    # 词界匹配:fed/recession/crash/tariff/war 等——禁 banks?/markets?/strikes? 宽词
    # (曾把 National Bank Open / 电竞 BO3 误收入 event)
    _EVENT_RX = re.compile(
        r"\b(fed|fomc|interest\s*rates?|rate\s*cut|rate\s*hike|recession|inflation|"
        r"cpi|gdp|tariffs?|crash|correction|s&p|sp\s*500|nasdaq|treasury|yields?|"
        r"opec|crude\s*oil|debt\s*ceiling|government\s*shutdown|default|"
        r"nuclear|wars?|invasion|sanctions?|geopolitic\w*|"
        r"china|hong\s*kong|taiwan|brazil|india|japan|yuan|renminbi|pboc|boj|"
        r"emerging\s*markets?)\b",
        re.I,
    )
    _SPORT_RX = re.compile(
        r"\b(vs\.?|bo[123]|ufc|nba|nfl|mlb|nhl|atp|wta|open:|grand\s*slam|"
        r"counter-?strike|dota|lol|esport|tennis|football|soccer|match)\b",
        re.I,
    )
    def go():
        u = ("https://gamma-api.polymarket.com/markets"
             "?closed=false&order=volume24hr&ascending=false&limit=100")
        data = json.loads(_get(u))
        out, n_top = [], 0
        for mkt in data:
            try:
                vol = float(mkt.get("volume24hr") or 0)
                if vol < 50000:
                    continue
                q = (mkt.get("question") or "")[:160]
                is_event = bool(_EVENT_RX.search(q)) and not _SPORT_RX.search(q)
                if not is_event:
                    if n_top >= 12:
                        continue
                    n_top += 1
                prices = mkt.get("outcomePrices")
                if isinstance(prices, str):
                    prices = json.loads(prices)
                if not prices:
                    _log_skip("polymarket_odds", q or "?", "no outcome prices")
                    continue
                out.append({"q": q, "bucket": "event" if is_event else "top",
                            "implied": prices, "vol24h": round(vol),
                            "ends": (mkt.get("endDate") or "")[:10]})
            except Exception as e:
                _log_skip("polymarket_odds", mkt.get("question", "?"), e)
                continue
        return out
    return _wrap("polymarket_odds", go)



# 十二爬虫(#11 liquidity 按需;#12 sectors);本机保留 ssl/FRED 回退/Alpaca 优先
ALL = [fetch_treasury_yields, fetch_fred, fetch_indices, fetch_edgar_recent,
       fetch_fda_press, fetch_commodities, fetch_polymarket, fetch_hedge_assets,
       fetch_fear_greed, fetch_earnings_calendar, fetch_sectors]


def run_all():
    SKIPS.clear()
    return [f() for f in ALL]
