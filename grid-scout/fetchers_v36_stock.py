"""fetchers.py —— 晚报确定性采集层(零 LLM,零爬虫,全官方/公开源)。
每源:try/except → {source, ok, ts, items[]};失败如实入记录,不静默。
铁则:FRED 需免费 API key(可选源,缺 key 自动跳过并如实记录);
     其余源零注册。守恒手写 v1,离线开发,首跑即验收。"""
from __future__ import annotations
import datetime, json, os, re, urllib.request

UA = {"User-Agent": "grid-evening-scout/1.0 (research; contact: local)"}
SKIPS: list = []          # 本轮逐条跳过记录,与 raw 同文件落盘(侯三审:不许静默吞)


def _log_skip(source, item, reason):
    SKIPS.append({"source": source, "item": str(item)[:80], "reason": str(reason)[:200],
                  "ts": datetime.datetime.now().astimezone().isoformat()})
TIMEOUT = 20


def _get(url, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
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





def _stooq_daily(sym, name, skip_src):
    """stooq 日线末两行 → OHLC + 确定性衍生读数(数字出引擎,解读归 DS):
    chg_pct=对昨收涨跌%;close_loc=收盘位于日内区间位置(0=贴最低,1=贴最高);
    tape_flag=冲高回落(日高破昨收但收盘落回区间下 40%,机构拉高出货的典型日线形)
             /强势收高(收盘贴顶且收涨)/空串。"""
    try:
        rows = _get(f"https://stooq.com/q/d/l/?s={sym}&i=d").strip().splitlines()
        if len(rows) < 3:
            _log_skip(skip_src, sym, "csv too short")
            return None
        head = rows[0].split(",")
        prev = dict(zip(head, rows[-2].split(",")))
        last = dict(zip(head, rows[-1].split(",")))
        o, h, l, c = (float(last[k]) for k in ("Open", "High", "Low", "Close"))
        pc = float(prev["Close"])
        d = {"name": name, "date": last.get("Date"), "open": o, "high": h, "low": l, "close": c,
             "chg_pct": round((c / pc - 1) * 100, 2),
             "close_loc": round((c - l) / (h - l), 2) if h > l else None}
        d["tape_flag"] = ("冲高回落" if (h > pc and d["close_loc"] is not None and d["close_loc"] < 0.4)
                          else ("强势收高" if (d["close_loc"] or 0) > 0.8 and c > pc else ""))
        return d
    except Exception as e:
        _log_skip(skip_src, sym, e)
        return None


def fetch_indices():
    """爬虫#3:SP500/Nasdaq/VIX 指数日线 + tape 读数(stooq,零 key)。"""
    def go():
        out = [_stooq_daily(sym, name, "indices")
               for sym, name in (("^spx", "SP500"), ("^ndq", "NASDAQ"), ("^vix", "VIX"))]
        return [x for x in out if x]
    return _wrap("indices", go)


def fetch_hedge_assets():
    """爬虫#8:对冲资产日线(GLD/SLV/OXY/USO,stooq 零 key)——
    Lyra 拍板 2026-08-05:拉高出货/黑天鹅出尽情形要补贵金属/原油对冲,
    对冲腿评估必须有实测读数可锚,不许凭记忆。"""
    def go():
        spec = [("gld.us","GLD","hedge"),("slv.us","SLV","hedge"),("oxy.us","OXY","hedge"),
                ("uso.us","USO","hedge"),("tlt.us","TLT","hedge"),("uup.us","UUP","hedge"),
                # 资金迁徙目的地(Lyra 2026-08-05:资金不会消失只会转移——海外/ADR)
                ("fxi.us","FXI","rotation"),("kweb.us","KWEB","rotation"),
                ("ewz.us","EWZ","rotation"),("ewj.us","EWJ","rotation"),
                ("eem.us","EEM","rotation"),("baba.us","BABA","rotation")]
        out = []
        for sym, name, cls in spec:
            d = _stooq_daily(sym, name, "hedge_assets")
            if d:
                d["cls"] = cls
                out.append(d)
        return out
    return _wrap("hedge_assets", go)


def fetch_fear_greed():
    """爬虫#9:CNN Fear & Greed(公开 dataviz 端点,零 key)——
    贪婪极值 + 指数冲高回落 = 拉高出货语境的情绪腿;端点若变响亮入 skip。"""
    def go():
        data = json.loads(_get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata"))
        fg = data.get("fear_and_greed") or {}
        if not fg:
            _log_skip("fear_greed", "graphdata", "empty fear_and_greed")
            return []
        return [{"score": fg.get("score"), "rating": fg.get("rating"),
                 "prev_close": fg.get("previous_close"),
                 "prev_1w": fg.get("previous_1_week"), "prev_1m": fg.get("previous_1_month")}]
    return _wrap("fear_greed", go)


def fetch_polymarket():
    """Polymarket 事件赔率(Gamma 公开 API,无 key)。读数规则:市场隐含概率≠真实概率——
    薄市场不可靠、UMA 结算风险、对冲盘含风险溢价(类比 IV 的 VRP)。流动性地板挡薄市场。"""
    # 词界匹配:裸子串会误伤(award 含 war、corporate 含 rate——被功能测试抓获)
    _EVENT_RX = re.compile(
        r"\b(fed|rates?|fomc|recession|inflation|cpi|gdp|tariffs?|crash|correction"
        r"|s&p|sp ?500|nasdaq|stocks?|markets?|treasury|yields?|oil|opec|gold|bitcoin"
        r"|etf|shutdown|default|banks?|nuclear|strikes?|wars?|invasion"
        r"|china|hong ?kong|taiwan|brazil|india|japan|yuan|renminbi|pboc|boj"
        r"|emerging markets?)\b", re.I)
    def go():
        u = ("https://gamma-api.polymarket.com/markets"
             "?closed=false&order=volume24hr&ascending=false&limit=100")
        data = json.loads(_get(u))
        out, n_top = [], 0
        for mkt in data:
            try:
                vol = float(mkt.get("volume24hr") or 0)
                if vol < 50000:
                    continue                      # 地板挡薄市场,属设计不属异常,不入 skip
                q = (mkt.get("question") or "")[:160]
                is_event = bool(_EVENT_RX.search(q))
                if not is_event:
                    if n_top >= 12:               # 非事件类只留头部热度,事件类(宏观/市场/地缘)全收
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


# 九爬虫全员(Lyra 拍板 2026-08-05)
ALL = [fetch_treasury_yields, fetch_fred, fetch_indices, fetch_edgar_recent,
       fetch_fda_press, fetch_commodities, fetch_polymarket, fetch_hedge_assets, fetch_fear_greed]


def run_all():
    SKIPS.clear()
    return [f() for f in ALL]
