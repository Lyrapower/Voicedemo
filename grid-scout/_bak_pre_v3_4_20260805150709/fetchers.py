"""fetchers.py —— 晚报确定性采集层(零 LLM,零爬虫,全官方/公开源)。
每源:try/except → {source, ok, ts, items[]};失败如实入记录,不静默。
铁则:FRED 需免费 API key(可选源,缺 key 自动跳过并如实记录);
     其余源零注册。守恒手写 v1,离线开发,首跑即验收。"""
from __future__ import annotations
import datetime, json, os, ssl, urllib.request

UA = {"User-Agent": "grid-evening-scout/1.0 (research; contact: local)"}
SKIPS: list = []          # 本轮逐条跳过记录,与 raw 同文件落盘(侯三审:不许静默吞)


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


def fetch_fred():
    """FRED:失业率 UNRATE、CPI 同比、联邦基金利率(需免费 key,缺则跳过)。"""
    key = os.getenv("FRED_API_KEY", "").strip()
    def go():
        if not key:
            raise RuntimeError("FRED_API_KEY not set, skipped(设计如此,免费注册后填 .env 即启)")
        out = []
        for sid in ("UNRATE", "FEDFUNDS", "CPIAUCSL"):
            u = ("https://api.stlouisfed.org/fred/series/observations?series_id=%s"
                 "&api_key=%s&file_type=json&sort_order=desc&limit=2" % (sid, key))
            obs = json.loads(_get(u))["observations"]
            out.append({"series": sid, "latest": obs[0], "prev": obs[1] if len(obs) > 1 else None})
        return out
    return _wrap("fred_macro", go)


def fetch_edgar_recent():
    """EDGAR 全文检索:近两日 8-K/425(并购信号高发表格)。官方,需 UA。"""
    def go():
        frm = (datetime.date.today() - datetime.timedelta(days=2)).isoformat()
        u = ("https://efts.sec.gov/LATEST/search-index?q=%22merger%20agreement%22&forms=8-K"
             f"&startdt={frm}&enddt={datetime.date.today().isoformat()}")
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
        out.append({
            "name": name,
            "Date": day,
            "Close": str(round(float(close), 4)),
            "source": "alpaca",
            "proxy": sym,
            "feed": feed,
            "note": note,
        })
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


def fetch_polymarket():
    """Polymarket 事件赔率(Gamma 公开 API,无 key)。读数规则:市场隐含概率≠真实概率——
    薄市场不可靠、UMA 结算风险、对冲盘含风险溢价(类比 IV 的 VRP)。流动性地板挡薄市场。"""
    def go():
        u = ("https://gamma-api.polymarket.com/markets"
             "?closed=false&order=volume24hr&ascending=false&limit=25")
        data = json.loads(_get(u))
        out = []
        for mkt in data:
            try:
                vol = float(mkt.get("volume24hr") or 0)
                if vol < 50000:
                    continue                      # 地板挡薄市场,属设计不属异常,不入 skip
                prices = mkt.get("outcomePrices")
                if isinstance(prices, str):
                    prices = json.loads(prices)
                if not prices:
                    _log_skip("polymarket_odds", mkt.get("question", "?"), "no outcome prices")
                    continue
                out.append({"q": (mkt.get("question") or "")[:160],
                            "implied": prices, "vol24h": round(vol),
                            "ends": (mkt.get("endDate") or "")[:10]})
            except Exception as e:
                _log_skip("polymarket_odds", mkt.get("question", "?"), e)
                continue
        return out
    return _wrap("polymarket_odds", go)


ALL = [fetch_treasury_yields, fetch_fred, fetch_indices, fetch_edgar_recent, fetch_fda_press, fetch_commodities, fetch_polymarket]


def run_all():
    SKIPS.clear()
    return [f() for f in ALL]
