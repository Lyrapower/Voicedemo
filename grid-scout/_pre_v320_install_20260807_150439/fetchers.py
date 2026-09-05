"""fetchers.py · integrated v1 + Alpaca tape(用户指令 2026-08-07)。

基座 = Downloads「fetchers integrated v1」:
  · EDGAR 交易日锚定 + API 软失败入 skip
  · afterhours 带 asof(Nasdaq quote info)
  · earnings_calendar seen_days + 昨+今热日
  · 守恒四点 afterhours/EDGAR 合并

主 tape(指数/对冲/板块/商品/个股快照) = 本机 Alpaca quote_layer(门禁)。
**不**回滚 integrated 文内 stooq 日线路径——Alpaca 为现网主路径。
另保留:et_now_hm · ssl/certifi · FRED API→BLS/NYFed 回退 · LIQ_MCAP_FLOOR_B。
"""
from __future__ import annotations
import datetime, json, os, re, ssl, urllib.request
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

def et_now_hm():
    """当前 ET 钟点 HH:MM(prompt/渲染共用,杜绝硬编码 9:45)。v3.13。"""
    if _ET is None:
        return datetime.datetime.now().strftime("%H:%M") + "(本机时区,ZoneInfo 不可用)"
    return datetime.datetime.now(_ET).strftime("%H:%M")


UA = {"User-Agent": "grid-evening-scout/1.0 (research; contact: local)"}
SKIPS: list = []          # 本轮逐条跳过记录,与 raw 同文件落盘(侯三审:不许静默吞)
LIQ_MCAP_FLOOR_B = float(os.getenv("LIQ_MCAP_FLOOR_B", "2.0"))

UA = {"User-Agent": "grid-evening-scout/1.0 (research; contact: local)"}
SKIPS: list = []          # 本轮逐条跳过记录,与 raw 同文件落盘(侯三审:不许静默吞)
LIQ_MCAP_FLOOR_B = float(os.getenv("LIQ_MCAP_FLOOR_B", "2.0"))


def _log_skip(source, item, reason):
    SKIPS.append({"source": source, "item": str(item)[:80], "reason": str(reason)[:200],
                  "ts": datetime.datetime.now().astimezone().isoformat()})
TIMEOUT = 20

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
        # earnings_calendar 热日单日可 500+ 行;全局 40/240 会吞掉今日 AMC(TEAM 案例)
        # 热日解封后昨+今可 >800;按市值排序后前 240 多为 time-not-supplied 巨头,
        # 中盘 AMC(after) 被裁掉 → movers/amc_tonight 空。cap=1200 守恒判例。
        cap = 1200 if source == "earnings_calendar" else 40
        return {"source": source, "ok": True, "ts": ts, "items": items[:cap]}
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
    检索窗随交易日锚定(时间语义家族收尾:UTC 机器晚班不漂"明天")。"""
    def go():
        base = trading_date()
        frm = (base - datetime.timedelta(days=2)).isoformat()
        u = ("https://efts.sec.gov/LATEST/search-index?q=%22merger%20agreement%22&forms=8-K"
             f"&startdt={frm}&enddt={base.isoformat()}")
        try:
            data = json.loads(_get(u))
        except Exception as e:
            _log_skip("edgar_ma_8k", "api", e)
            return []
        hits = data.get("hits", {}).get("hits", [])
        out = []
        for h in hits:
            src = h.get("_source", {})
            names = src.get("display_names") or ["?"]
            out.append({
                "company": names[0],
                "form": src.get("file_type"),
                "filed": src.get("file_date")
            })
        return out
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

def _load_alpaca_keys():
    """优先进程环境;否则从本仓已有 .env 读(不打印值)。
    v3.16§⑦:统一接受 ALPACA_KEY_ID / ALPACA_SECRET_KEY(兼旧名 ALPACA_API_KEY)。"""
    key = sec = ""
    for n in _ALPACA_KEY_NAMES:
        key = os.getenv(n, "").strip()
        if key:
            break
    for n in _ALPACA_SEC_NAMES:
        sec = os.getenv(n, "").strip()
        if sec:
            break
    if key and sec:
        return key, sec
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, ".env"),
        os.path.join(here, "..", "aether_nexus", ".env"),
        os.path.join(here, "..", "alpha-platform", ".env"),
    ]
    found = {}
    want = set(_ALPACA_KEY_NAMES) | set(_ALPACA_SEC_NAMES)
    for path in candidates:
        try:
            with open(path, encoding="utf-8") as f:
                for ln in f:
                    s = ln.strip()
                    if not s or s.startswith("#") or "=" not in s:
                        continue
                    k, _, v = s.partition("=")
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k in want and v and k not in found:
                        found[k] = v
        except OSError:
            continue
        if any(found.get(n) for n in _ALPACA_KEY_NAMES) and any(
            found.get(n) for n in _ALPACA_SEC_NAMES
        ):
            break
    for n in _ALPACA_KEY_NAMES:
        key = found.get(n, "") or key
        if key:
            break
    for n in _ALPACA_SEC_NAMES:
        sec = found.get(n, "") or sec
        if sec:
            break
    return key, sec

def alpaca_feed():
    """账户实况 feed 档(不预设;env ALPACA_DATA_FEED,默认 iex)。"""
    return (os.getenv("ALPACA_DATA_FEED") or "iex").strip() or "iex"

def feed_ah_label():
    """盘后口径标签——跟 feed 档走,守恒不猜。"""
    return "盘后·SIP 合并带" if alpaca_feed().lower() == "sip" else "盘后·IEX 口径"

def data_plane_banner():
    """启动横幅:当班数据源 + feed 档。stooq 已退役。"""
    key, sec = _load_alpaca_keys()
    if key and sec:
        return ("Alpaca feed=%s · %s · 全线主路径; "
                "指数=SPY/QQQ/VIXY · 商品=USO/GLD(ETF代理); stooq 已退役"
                % (alpaca_feed(), feed_ah_label()))
    return "Alpaca 未配置 · 指数/商品/个股均无主路径(stooq 已退役,不会回退)"

def _utc_iso_to_et_hm(iso_ts):
    """ISO UTC → ET HH:MM;失败返回空串。"""
    if not iso_ts or len(str(iso_ts)) < 16:
        return ""
    try:
        s = str(iso_ts).replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        if _ET is not None:
            return dt.astimezone(_ET).strftime("%H:%M")
        return dt.astimezone(datetime.timezone.utc).strftime("%H:%M") + "Z"
    except Exception:
        return ""

def quote_layer_bars(symbol, limit=60):
    """个股日线收盘缝(今日实现=Alpaca)。换 API 只改此函数内脏。
    必须 sort=desc:asc+start+limit 会吃到最旧 N 根(与 alpha daily_bars 同坑)。"""
    key, sec = _load_alpaca_keys()
    sym = (symbol or "").upper()
    if not (key and sec) or not sym:
        return []
    start = (trading_date() - datetime.timedelta(days=400)).isoformat() + "T00:00:00Z"
    feed = alpaca_feed()
    lim = max(int(limit or 60), 60)
    url = ("https://data.alpaca.markets/v2/stocks/%s/bars"
           "?timeframe=1Day&start=%s&limit=%d&adjustment=raw&feed=%s&sort=desc"
           % (sym, start, lim, feed))
    req = urllib.request.Request(
        url, headers={**UA, "APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_context()) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        _log_skip("quote_layer.bars", sym, e)
        return []
    seq = []
    for b in (data.get("bars") or []):
        try:
            seq.append(float(b["c"]))
        except (KeyError, TypeError, ValueError):
            pass
    seq.reverse()  # 时间正序供 RSI/mom20
    return seq

def quote_layer_snapshot(symbols, *, with_rsi=True):
    """个股/ETF 快照缝(今日实现=Alpaca 批量 snapshot)。
    含 dailyBar/prevDailyBar/latestTrade/latestQuote;source+feed+盘后字段可对账。
    with_rsi=False:全宇宙扫描跳过逐票 bars(515×RSI 会拖死),前三席再单独补 RSI。
    换更好的数据 API 时只换本函数内脏——爬虫/引擎/渲染零改动。"""
    key, sec = _load_alpaca_keys()
    syms = [str(s).upper() for s in (symbols or []) if s]
    if not (key and sec) or not syms:
        return {}
    feed = alpaca_feed()
    label = feed_ah_label()
    out = {}
    for i in range(0, len(syms), 40):
        chunk = syms[i:i + 40]
        url = ("https://data.alpaca.markets/v2/stocks/snapshots?symbols="
               + ",".join(chunk))
        req = urllib.request.Request(
            url, headers={**UA, "APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec},
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_context()) as r:
                data = json.loads(r.read().decode())
        except Exception as e:
            _log_skip("quote_layer.snapshot", ",".join(chunk[:3]), e)
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
            trade = snap.get("latestTrade") or {}
            quote = snap.get("latestQuote") or {}
            trade_ts = str(trade.get("t") or "")
            quote_ts = str(quote.get("t") or "")
            item = {
                "ticker": sym, "name": sym, "date": day, "Date": day,
                "open": o, "high": h, "low": l, "close": c, "Close": str(round(c, 4)),
                "chg_pct": chg_pct, "close_loc": close_loc, "tape_flag": tape or "",
                "rsi14": None, "source": "alpaca", "proxy": sym,
                "feed": feed, "feed_label": label,
                "latest_trade_ts": trade_ts or None,
                "latest_trade_price": float(trade["p"]) if trade.get("p") is not None else None,
                "latest_quote_ts": quote_ts or None,
            }
            # 盘后:优先 latestTrade(≥20:00Z),否则 latestQuote mid
            ah_px, ah_ts = None, ""
            if len(trade_ts) >= 19 and trade_ts[11:19] >= "20:00:00" and trade.get("p") is not None:
                try:
                    ah_px, ah_ts = float(trade["p"]), trade_ts
                except (TypeError, ValueError):
                    pass
            if ah_px is None and len(quote_ts) >= 19 and quote_ts[11:19] >= "20:00:00":
                try:
                    ap, bp = float(quote["ap"]), float(quote["bp"])
                    if ap > 0 and bp > 0:
                        ah_px, ah_ts = (ap + bp) / 2.0, quote_ts
                        item["ah_bid"], item["ah_ask"] = round(bp, 4), round(ap, 4)
                except (KeyError, TypeError, ValueError):
                    pass
            if ah_px is not None and c > 0:
                item["ah_price"] = round(ah_px, 4)
                item["ah_ts"] = ah_ts
                item["ah_et_hm"] = _utc_iso_to_et_hm(ah_ts)
                item["ah_vs_rth_pct"] = round((ah_px / c - 1.0) * 100.0, 2)
                if pc:
                    item["ah_vs_prev_pct"] = round((ah_px / pc - 1.0) * 100.0, 2)
                item["ah_display"] = "盘后 %.2f(%s, %s ET)" % (
                    ah_px, label, item["ah_et_hm"] or "??:??",
                )
            out[sym] = item
    # RSI14 + v3.19 趋势读数 via quote_layer.bars(全宇宙扫描请 with_rsi=False)
    if with_rsi:
        for sym, it in list(out.items()):
            closes = quote_layer_bars(sym, limit=260)
            if len(closes) >= 15:
                it["rsi14"] = _rsi14(closes)
            elif closes:
                _log_skip("quote_layer.bars", sym, "closes=%d(<15, RSI null)" % len(closes))
            c = it.get("close")
            if c and closes:
                it["chg5_pct"] = (round((c / closes[-6] - 1) * 100, 2)
                                  if len(closes) >= 6 else None)
                it["mom20_pct"] = (round((c / closes[-21] - 1) * 100, 2)
                                   if len(closes) >= 21 else None)
                it["high52_dist_pct"] = (round((c / max(closes) - 1) * 100, 2)
                                         if closes else None)
    return out

class quote_layer:
    """v3.16§⑦ 换源唯一缝:snapshot(syms) / bars(sym)。今日内脏=Alpaca。"""
    snapshot = staticmethod(quote_layer_snapshot)
    bars = staticmethod(quote_layer_bars)

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

def fetch_commodities():
    """油/金环境——Alpaca ETF 代理(stooq 已退役):
    USO≈WTI 原油环境, GLD≈黄金环境。须在 note/proxy 标明非现货。"""
    def go():
        plan = (
            ("WTI", "USO", "USO ETF proxy for WTI crude env — not CL futures"),
            ("GOLD", "GLD", "GLD ETF proxy for gold env — not XAU spot"),
        )
        snaps = quote_layer.snapshot([p[1] for p in plan])
        out = []
        for name, sym, note in plan:
            it = snaps.get(sym)
            if not it:
                _log_skip("commodities", sym, "alpaca snapshot miss")
                continue
            d = dict(it)
            d["name"] = name
            d["proxy"] = sym
            d["note"] = note
            out.append(d)
        return out
    return _wrap("commodities", go)





_ALPACA_KEY_NAMES = ("ALPACA_KEY_ID", "ALPACA_API_KEY", "APCA_API_KEY_ID")
_ALPACA_SEC_NAMES = ("ALPACA_SECRET_KEY", "APCA_API_SECRET_KEY")

def _indices_from_alpaca():
    """指数环境 = Alpaca ETF 代理(stooq 已退役):
    SPY≈SP500, QQQ≈Nasdaq, VIXY≈波动率(非 CBOE VIX 现货,须标注)。"""
    key, sec = _load_alpaca_keys()
    if not (key and sec):
        _log_skip("indices", "alpaca", "ALPACA_KEY 未配置")
        return []
    plan = (
        ("SP500", "SPY", "SPY ETF proxy for SP500 env — not ^SPX"),
        ("NASDAQ", "QQQ", "QQQ ETF proxy for Nasdaq env — not ^NDX"),
        ("VIX", "VIXY", "VIXY ETF proxy — not CBOE VIX spot"),
        ("RSP", "RSP", "RSP equal-weight proxy — breadth vs SPY mom20"),
    )
    snaps = quote_layer.snapshot([p[1] for p in plan])
    out = []
    for name, sym, note in plan:
        it = snaps.get(sym)
        if not it:
            _log_skip("indices", sym, "alpaca snapshot miss")
            continue
        d = dict(it)
        d["name"] = name
        d["proxy"] = sym
        d["note"] = note
        out.append(d)
    return out

def _indices_from_yahoo():
    """Alpaca 失败时的零 key 回退(真指数 close)。"""
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
    """大盘/波动率:Alpaca ETF 代理主路径(SPY/QQQ/VIXY)→ Yahoo 回退。stooq 已退役。"""
    def go():
        out = _indices_from_alpaca()
        have = {x["name"] for x in out}
        if len(out) < 3:
            for it in _indices_from_yahoo():
                if it["name"] not in have:
                    out.append(it)
                    have.add(it["name"])
        return out
    return _wrap("indices", go)

_INDEX_PROXY = {
    "^spx": ("SPY", "SP500"), "^ndq": ("QQQ", "NASDAQ"), "^vix": ("VIXY", "VIX"),
    "rsp.us": ("RSP", "RSP"),
}


def _sym_to_alpaca_ticker(sym, name=""):
    """stooq 形符号 → Alpaca ticker。pltr.us→PLTR;指数走 ETF 代理。"""
    s = (sym or "").strip().lower()
    if s in _INDEX_PROXY:
        return _INDEX_PROXY[s][0]
    if s.endswith(".us"):
        return s[:-3].upper()
    if re.fullmatch(r"[A-Za-z]{1,5}", s or ""):
        return s.upper()
    n = (name or "").strip().upper()
    if re.fullmatch(r"[A-Z]{1,5}", n):
        return n
    return None


def _stooq_daily(sym, name, skip_src):
    """v3.19 兼容缝:原 stooq 日线调用 → Alpaca quote_layer(本机 stooq 已 JS 墙死)。
    字段对齐引擎:chg_pct/close_loc/rsi14/chg5_pct/mom20_pct/high52_dist_pct。"""
    ticker = _sym_to_alpaca_ticker(sym, name)
    if not ticker:
        _log_skip(skip_src, sym or name, "no alpaca ticker map")
        return None
    snaps = quote_layer_snapshot([ticker], with_rsi=True)
    it = snaps.get(ticker)
    if not it:
        _log_skip(skip_src, ticker, "alpaca snapshot miss")
        return None
    d = dict(it)
    d["name"] = name or ticker
    return d


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
    """兼容旧名 → quote_layer.snapshot(v3.16§⑦ 缝)。"""
    return quote_layer.snapshot(symbols)

def alpaca_daily_closes(symbols, limit=60):
    """兼容旧名 → quote_layer.bars 批量。"""
    out = {}
    for sym in [str(s).upper() for s in (symbols or []) if s]:
        seq = quote_layer.bars(sym, limit=limit)
        if len(seq) >= 15:
            out[sym] = seq
        elif seq:
            _log_skip("alpaca_bars", sym, "closes=%d(<15, RSI null)" % len(seq))
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
    """爬虫#8:对冲+迁徙资产——Alpaca/quote_layer 唯一路径(stooq 已退役)。"""
    def go():
        out = _hedge_from_alpaca()
        if len(out) < 4:
            _log_skip("hedge_assets", "plan", "alpaca legs<%d (stooq retired, no fill)" % len(out))
        return out
    return _wrap("hedge_assets", go)

def fetch_earnings_calendar():
    """爬虫#10:Nasdaq 财报日历——上一交易日+今起5日。
    热日(昨+今)不设 15/80 cap——DOCS(~$4B,+68% AH)等中盘暴动否则被掐(patch 判例);
    未来日维持 15;源级 wrap 须≥1200 以免热日全量再被吞。
    integrated v1:seen_days 防重复日。"""
    def go():
        out = []
        base = trading_date()
        days = [prev_trading_day(base)] + [base + datetime.timedelta(days=k) for k in range(5)]
        # 热日解封:movers/amc_tonight 原料日;巨头扎堆日中盘暴动段必须可见
        hot = {days[0], base}
        seen_days = set()
        for day_d in days:
            day = day_d.isoformat()
            if day in seen_days:
                continue
            seen_days.add(day)
            try:
                raw = json.loads(_get(
                    "https://api.nasdaq.com/api/calendar/earnings?date=" + day,
                    {"Accept": "application/json"},
                ))
                rows = (((raw or {}).get("data") or {}).get("rows")) or []
                def cap(r):
                    ds = "".join(ch for ch in (r.get("marketCap") or "") if ch.isdigit())
                    return int(ds) if ds else 0
                rows = sorted(rows, key=cap, reverse=True)
                if day_d not in hot:
                    rows = rows[:15]
                for r in rows:
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
    if not t:
        return None
    mult = 1.0
    if t[-1:].upper() in ("T", "B", "M", "K"):
        mult = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}[t[-1].upper()]
        t = t[:-1]
    try:
        val = float(t) * mult
        if val != val:  # NaN check
            return None
        return val
    except ValueError:
        return None

def fetch_afterhours(symbols):
    """按需(晚班):Nasdaq quote info 盘后/延时报价(零 key,流动性闸同源)——
    为 amc_tonight 名单取实测盘后涨跌,打掉"stooq 无盘后"的旧边界(DOCS +68% 案例)。
    secondaryData 缺失 = 无盘后读数,如实置 None,不编。
    仅晚班调用;盘中调用时 secondary 非盘后价,ah_chg_pct 语义不成立。"""
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
                           "asof": (d.get("secondaryData") or {}).get("lastTradeTimestamp"),
                           "ah_chg_pct": round((x / p - 1) * 100, 2) if (x and p) else None}
            except Exception as e:
                _log_skip("afterhours", sym, e)
                continue
            if got:
                out.append(got)
            else:
                _log_skip("afterhours", sym, "no secondaryData/price fields")
        return out
    return _wrap("afterhours", go)

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
    """爬虫#12:板块 tape(SPDR 11 + SMH)——Alpaca/quote_layer(stooq 已退役)。"""
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
            else:
                _log_skip("sectors", sym, "alpaca miss (stooq retired)")
        return out
    return _wrap("sectors", go)

def fetch_fear_greed():
    """爬虫#9:CNN Fear & Greed(公开 dataviz 端点,零 key)——
    贪婪极值 + 指数冲高回落 = 拉高出货语境的情绪腿;端点若变响亮入 skip。"""
    def go():
        try:
            data = json.loads(_get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata"))
        except Exception as e:
            _log_skip("fear_greed", "graphdata", e)
            return []
        fg = data.get("fear_and_greed") or {}
        if not fg:
            _log_skip("fear_greed", "graphdata", "empty fear_and_greed")
            return []
        score = fg.get("score")
        if isinstance(score, str):
            try:
                score = float(score)
            except ValueError:
                score = None
        return [{"score": score, "rating": fg.get("rating"),
                 "prev_close": fg.get("previous_close"),
                 "prev_1w": fg.get("previous_1_week"), "prev_1m": fg.get("previous_1_month")}]
    return _wrap("fear_greed", go)


LIQ_MCAP_FLOOR_B = float(os.getenv("LIQ_MCAP_FLOOR_B", "2.0"))

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

# 十二爬虫全员(#11 liquidity_gate 按需;#12 sectors) · tape=Alpaca · AH/日历=integrated
ALL = [fetch_treasury_yields, fetch_fred, fetch_indices, fetch_edgar_recent,
       fetch_fda_press, fetch_commodities, fetch_polymarket, fetch_hedge_assets,
       fetch_fear_greed, fetch_earnings_calendar, fetch_sectors]


def run_all():
    SKIPS.clear()
    return [f() for f in ALL]

