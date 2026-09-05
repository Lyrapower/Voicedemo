"""fetchers.py —— 晚报确定性采集层(零 LLM,零爬虫,全官方/公开源)。
每源:try/except → {source, ok, ts, items[]};失败如实入记录,不静默。
铁则:FRED 需免费 API key(可选源,缺 key 自动跳过并如实记录);
     其余源零注册。守恒手写 v1,离线开发,首跑即验收。"""
from __future__ import annotations
import datetime, json, os, re, urllib.request
try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:
    _ET = None


def trading_date():
    """美股交易日期(ET 定义,减 4 小时使 ET 0-4 点仍归前一交易日——
    21:00 PST 晚班 = 00:00 ET 不跨日)。机器时区无关:PST/UTC/Docker 结果一致。
    ZoneInfo 不可用则响亮回退本机日期(仅 PST 机器安全)。"""
    if _ET is None:
        print("[fetchers] ZoneInfo 不可用——回退本机日期(仅 PST 机器安全)")
        return datetime.date.today()
    return (datetime.datetime.now(_ET) - datetime.timedelta(hours=4)).date()


def prev_trading_day(d):
    """上一交易日(跳周末:周一→上周五)。节假日未处理——已知边界,不装。"""
    d = d - datetime.timedelta(days=1)
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d

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
        # 源级 cap 按源配置:earnings_calendar 热日解封后两天可 100+ 条,
        # 全局 40 会把未来日整段吃掉(同族第四层,2026-08-06 测试现形);其余源维持 40
        return {"source": source, "ok": True, "ts": ts,
                "items": items[:(240 if source == "earnings_calendar" else 40)]}
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





def _rsi14(closes):
    """Wilder RSI14(确定性;<15 根返回 None)。时机过滤器,非方向信号。"""
    if len(closes) < 15:
        return None
    gains = losses = 0.0
    for i in range(1, 15):
        ch = closes[i] - closes[i - 1]
        gains += max(ch, 0.0); losses += max(-ch, 0.0)
    ag, al = gains / 14, losses / 14
    for i in range(15, len(closes)):
        ch = closes[i] - closes[i - 1]
        ag = (ag * 13 + max(ch, 0.0)) / 14
        al = (al * 13 + max(-ch, 0.0)) / 14
    if al == 0:
        return 100.0
    return round(100 - 100 / (1 + ag / al), 1)


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
        ci = head.index("Close")
        closes = []
        for r in rows[-61:][1:] if len(rows) <= 61 else rows[-60:]:
            try:
                closes.append(float(r.split(",")[ci]))
            except (ValueError, IndexError):
                pass
        d = {"name": name, "date": last.get("Date"), "open": o, "high": h, "low": l, "close": c,
             "chg_pct": round((c / pc - 1) * 100, 2),
             "rsi14": _rsi14(closes),
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


LIQ_MCAP_FLOOR_B = float(os.getenv("LIQ_MCAP_FLOOR_B", "2.0"))


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
    """爬虫#11(按需,Lyra 批 2026-08-06):Nasdaq summary 端点查市值/日均量——
    流动性闸的牙。候选出现才查,不进夜间轮询;股票查不到回退 ETF assetclass;
    仍查不到 = None(不装数),失败响亮入 skip。"""
    def go():
        out = []
        for sym in symbols:
            item = None
            for ac in ("stocks", "etf"):
                try:
                    raw = json.loads(_get("https://api.nasdaq.com/api/quote/%s/summary?assetclass=%s" % (sym, ac),
                                          {"Accept": "application/json"}))
                    sd = ((raw or {}).get("data") or {}).get("summaryData") or {}
                    mc = _parse_money((sd.get("MarketCap") or {}).get("value"))
                    av = _parse_money((sd.get("AverageVolume") or {}).get("value"))
                    if mc or av:
                        item = {"symbol": sym, "assetclass": ac,
                                "mcap_b": round(mc / 1e9, 2) if mc else None,
                                "avg_vol": int(av) if av else None}
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
    """爬虫#12:板块 tape(SPDR 11 板块 + SMH,stooq 同源零 key,非新依赖)——
    堵 8-06 现网案例:引擎无板块读数,"轮动"无从谈起。"""
    def go():
        spec = [("xlk.us", "XLK科技"), ("xlc.us", "XLC通信"), ("xly.us", "XLY可选消费"),
                ("xlp.us", "XLP必选消费"), ("xle.us", "XLE能源"), ("xlf.us", "XLF金融"),
                ("xlv.us", "XLV医疗"), ("xli.us", "XLI工业"), ("xlb.us", "XLB材料"),
                ("xlre.us", "XLRE地产"), ("xlu.us", "XLU公用"), ("smh.us", "SMH半导体")]
        out = [_stooq_daily(sym, name, "sectors") for sym, name in spec]
        return [x for x in out if x]
    return _wrap("sectors", go)


def fetch_afterhours(symbols):
    """按需(晚班):Nasdaq quote info 盘后/延时报价(零 key,流动性闸同源)——
    为 amc_tonight 名单取实测盘后涨跌,打掉"stooq 无盘后"的旧边界(DOCS +68% 案例)。
    secondaryData 缺失 = 无盘后读数,如实置 None,不编。"""
    def go():
        out = []
        for sym in symbols:
            got = None
            try:
                raw = json.loads(_get("https://api.nasdaq.com/api/quote/%s/info?assetclass=stocks" % sym,
                                      {"Accept": "application/json"}))
                d = (raw or {}).get("data") or {}
                p = _parse_money(((d.get("primaryData") or {}).get("lastSalePrice")))
                x = _parse_money(((d.get("secondaryData") or {}).get("lastSalePrice")))
                if p:
                    got = {"symbol": sym, "close": p, "ah_last": x,
                           "ah_chg_pct": round((x / p - 1) * 100, 2) if (x and p) else None}
            except Exception:
                pass
            if got:
                out.append(got)
            else:
                _log_skip("afterhours", sym, "no quote data")
        return out
    return _wrap("afterhours", go)


def fetch_earnings_calendar():
    """爬虫#10:Nasdaq 财报日历(今起5个自然日,零 key)——财报两步手册的数据前提。
    每日按市值取前15;端点变更/空日响亮入 skip。"""
    def go():
        out = []
        base = trading_date()
        # 上一交易日打头(跳周末,周一取上周五)——昨夜 AMC 是今晨最重要队列(TEAM 案例)
        days = [prev_trading_day(base)] + [base + datetime.timedelta(days=k) for k in range(5)]
        # 热日(上一交易日+今日)= movers/amc_tonight 的原料日,不设 15 cap——
        # 巨头扎堆日 ~$40B 中盘(暴动高发段)会在 cap 层被掐,下游排得再对也看不见(隔壁 Fable 抓获);
        # 未来日维持 cap(纯前瞻参考,量无意义)
        hot = {days[0], base}
        for day_d in days:
            day = day_d.isoformat()
            try:
                raw = json.loads(_get("https://api.nasdaq.com/api/calendar/earnings?date=" + day,
                                      {"Accept": "application/json"}))
                rows = (((raw or {}).get("data") or {}).get("rows")) or []
                def cap(r):
                    ds = "".join(ch for ch in (r.get("marketCap") or "") if ch.isdigit())
                    return int(ds) if ds else 0
                rows = sorted(rows, key=cap, reverse=True)
                if day_d not in hot:
                    rows = rows[:15]
                for r in rows:
                    out.append({"symbol": r.get("symbol"), "name": (r.get("name") or "")[:40],
                                "date": day, "when": r.get("time")})
            except Exception as e:
                _log_skip("earnings_calendar", day, e)
        return out
    return _wrap("earnings_calendar", go)


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


# 十二爬虫全员(#11 liquidity_gate 按需;#12 sectors 2026-08-06 TEAM 案例后加)
ALL = [fetch_treasury_yields, fetch_fred, fetch_indices, fetch_edgar_recent,
       fetch_fda_press, fetch_commodities, fetch_polymarket, fetch_hedge_assets,
       fetch_fear_greed, fetch_earnings_calendar, fetch_sectors]


def run_all():
    SKIPS.clear()
    return [f() for f in ALL]
