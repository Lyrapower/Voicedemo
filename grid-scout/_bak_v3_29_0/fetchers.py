"""fetchers.py · v3.25 —— FMP 付费档端点路由(Lyra 拍板 2026-08-19;主源架构 2026-08-17)。

数据层拓扑:
  主 tape(指数/对冲/板块/商品/个股)= FMP 付费档(端点自探定版 .fmp_route,legacy/stable 双族;
  每分钟令牌节流 FMP_RATE_PER_MIN 默认 280;预算 FMP_DAILY_BUDGET;本地 K 线缓存带血统+调用记账)
  第二源 = ThetaData(本地 Theta Terminal :25503,实跑口;未起则整链跳过响亮记录,不强迫起容器)
  backup = Alpaca(票级回退,现场 0817 版代码收编);stooq 已移除,不回退。
  换更好的数据 API:只换 quote_layer 内脏(_history/_fmp_quote)——爬虫/引擎/渲染零改动。
基座 = 现场 fetchers 0817_1108(integrated v1 + Alpaca):
  EDGAR 交易日锚定 · afterhours 带 asof · earnings_calendar seen_days+热日+wrap 1200(≥800 门禁)
  et_now_hm · ssl/certifi · FRED API→BLS/NYFed 回退 · feed 档标签 · LIQ 地板。
v3.24 复活的读数(Alpaca 过渡层曾静默丢失):vol_x20/on20/in20/_rets20/chg5/mom20/
  high52_dist + 真指数 ^GSPC/^IXIC/^VIX(替回 SPY/QQQ/VIXY 代理)+ HYG/LQD 信用金丝雀。
"""
from __future__ import annotations
import datetime, json, os, re, ssl, time, urllib.error, urllib.parse, urllib.request
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


def et_now_hm():
    """当前 ET 钟点 HH:MM(prompt/渲染共用,杜绝硬编码 9:45)。v3.13。"""
    if _ET is None:
        return datetime.datetime.now().strftime("%H:%M") + "(本机时区,ZoneInfo 不可用)"
    return datetime.datetime.now(_ET).strftime("%H:%M")


UA = {"User-Agent": "grid-evening-scout/1.0 (research; contact: local)"}
SKIPS: list = []          # 本轮逐条跳过记录,与 raw 同文件落盘(侯三审:不许静默吞)
TIMEOUT = 20


def _log_skip(source, item, reason):
    SKIPS.append({"source": source, "item": str(item)[:80], "reason": str(reason)[:200],
                  "ts": datetime.datetime.now().astimezone().isoformat()})


def liq_mcap_floor_b():
    """流动性地板(env 可调)。v3.24:改调用期读取——模块级快照在 .env 加载前定死,
    .env 里的 LIQ_MCAP_FLOOR_B 曾是死键(env 快照族,与 DS_KEY 同族一次治)。"""
    return float(os.getenv("LIQ_MCAP_FLOOR_B", "2.0"))


LIQ_MCAP_FLOOR_B = liq_mcap_floor_b()   # 兼容旧引用;新代码一律走 liq_mcap_floor_b()


def pool_price_floor():
    """候选地板·价格(v3.26,Lyra 2026-08-24:"10 块钱以下的没有任何流通率的"不许进推荐)。
    env POOL_PRICE_FLOOR,默认 10.0 美元;引擎级硬地板,名单/候选池/DS 点名三处同判。"""
    return float(os.getenv("POOL_PRICE_FLOOR", "10.0"))


def pool_adv_floor_usd():
    """候选地板·20 日平均成交额(美元,实测自日线 close×volume,末根未收不计)。
    env POOL_ADV_FLOOR_USD,默认 1e8($100M/日);无实测 = 不过地板(不装数)。"""
    return float(os.getenv("POOL_ADV_FLOOR_USD", "100000000"))


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
        # earnings_calendar 热日单日可 500+ 行;全局 40/240 会吞掉今日 AMC(TEAM 案例)。
        # 热日解封后昨+今可 >800;按市值排序后前 240 多为 time-not-supplied 巨头,
        # 中盘 AMC(after) 被裁掉 → movers/amc_tonight 空。cap=1200(≥800 门禁)守恒判例。
        # v3.26:movers 榜 50/侧(100 行)——FMP 按 % 排,$3 壳票 +80% 常占满前 20,
        # $12 的 +15% 真流动票被裁在榜外(ASST 型盲区);候选池地板在引擎侧筛。
        cap = 1200 if source == "earnings_calendar" else (120 if source == "market_movers" else 40)
        return {"source": source, "ok": True, "ts": ts, "items": items[:cap]}
    except Exception as e:
        return {"source": source, "ok": False, "ts": ts, "error": str(e)[:300], "items": []}


# ============================================================================
# quote_layer v3.24 —— FMP 主源 + 本地缓存 + 调用记账;Alpaca 票级 backup(v3.16§⑦ 缝)
# ============================================================================
PRICES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prices")
_FMP_LEDGER = {"date": "", "calls": 0}
_FMP_BATCH_OK = True     # 免费档批量 quote 若被拒(402/403),本班自动退单票循环
_QUOTE_MEMO: dict = {}   # 本班进程 memo:同一票不重复打点(装机自检/重跑均省配额)


def _fmp_key():
    return os.getenv("FMP_API_KEY", "").strip()


def _fmp_base():
    return os.getenv("FMP_BASE", "https://financialmodelingprep.com/api/v3").rstrip("/")


_FMP_STABLE_BASE = "https://financialmodelingprep.com/stable"
# 端点候选:legacy(/api/v3)与 stable 两族。V6 实证(2026-08-19):新账号付费 key 在
# legacy 上对指数/商品类返回 402 Payment Required。真相由回包定:首个出数的族按
# (kind:类) 定版落盘 .fmp_route 跨班续用,失效自愈重探(.theta_route 同判例 v3.24.2)。
_FMP_ROUTE = {}            # {"quote:index": "stable"|"legacy"};"" = 本班该类停用(不落盘)
_FMP_ROUTE_LOADED = [False]
_FMP_CALL_TS = []          # 每分钟节流窗口(付费档 300/min,默认留余量)
_FMP_UPGRADE_TRIED = set() # backup 血统缓存每班先试主源升级(一票一次)


def _fmp_route_file():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), ".fmp_route")


def _fmp_route_load():
    if not _FMP_ROUTE_LOADED[0]:
        _FMP_ROUTE_LOADED[0] = True
        try:
            doc = json.load(open(_fmp_route_file(), encoding="utf-8"))
            _FMP_ROUTE.update({k: v for k, v in doc.items() if isinstance(v, str) and v})
        except Exception:
            pass
    return _FMP_ROUTE


def _fmp_route_save():
    try:
        json.dump({k: v for k, v in _FMP_ROUTE.items() if v},
                  open(_fmp_route_file(), "w", encoding="utf-8"))
    except Exception:
        pass


def _fmp_class(sym):
    s = str(sym or "").upper()
    if s.startswith("^"):
        return "index"
    if s in ("CLUSD", "GCUSD"):
        return "commodity"
    return "stock"


def _http_err_text(e):
    """HTTP 错误 → 'HTTP 402 <正文前120字>':报错透明,原文进 skips(禁静默吞码)。"""
    try:
        code = getattr(e, "code", None)
        body = ""
        if hasattr(e, "read"):
            try:
                body = e.read(300).decode("utf-8", "replace").strip()
            except Exception:
                body = ""
        return ("HTTP %s %s" % (code, body[:120])).strip() if code else str(e)[:160]
    except Exception:
        return str(e)[:160]


def _fmp_pace():
    """每分钟令牌节流:付费档限 300 次/分,默认 280 留余量(FMP_RATE_PER_MIN 可调)。
    首拉全量串行连发曾可撞限出 429 连环——v3.25 匀速根治。"""
    limit = max(1, int(os.getenv("FMP_RATE_PER_MIN", "280")))
    while True:
        now = time.time()
        while _FMP_CALL_TS and now - _FMP_CALL_TS[0] > 60:
            _FMP_CALL_TS.pop(0)
        if len(_FMP_CALL_TS) < limit:
            _FMP_CALL_TS.append(now)
            return
        time.sleep(min(2.0, max(0.05, 60.0 - (now - _FMP_CALL_TS[0]) + 0.02)))


def _ledger_path():
    return os.path.join(PRICES_DIR, "_fmp_ledger.json")


def _ledger_load():
    global _FMP_LEDGER
    today = datetime.date.today().isoformat()   # FMP 配额按自然日,非交易日
    if _FMP_LEDGER["date"] != today:
        _FMP_LEDGER = {"date": today, "calls": 0}
        try:
            j = json.load(open(_ledger_path(), encoding="utf-8"))
            if j.get("date") == today:
                _FMP_LEDGER = j
        except Exception:
            pass
    return _FMP_LEDGER


def fmp_calls_today():
    return _ledger_load().get("calls", 0)


def _fmp_tick():
    led = _ledger_load()
    led["calls"] = int(led.get("calls", 0)) + 1
    try:
        os.makedirs(PRICES_DIR, exist_ok=True)
        json.dump(led, open(_ledger_path(), "w", encoding="utf-8"))
    except Exception:
        pass
    budget = int(os.getenv("FMP_DAILY_BUDGET", "250"))  # 付费档升级后只改这个 env
    warn = int(os.getenv("FMP_DAILY_WARN", str(max(1, budget * 4 // 5))))
    if led["calls"] == warn:
        print("[fetchers] ⚠ FMP 当日用量达 %d(当日预算 %d)——只记账不设闸,拍板在 Lyra" % (warn, budget))
    return led["calls"]


def _fmp_get(path_q):
    """FMP GET(节流+记账+带 key)。key 缺失直接抛——上游按票级回退处理。
    path_q 可为相对路径(挂 legacy base)或完整 URL(路由器给)。"""
    key = _fmp_key()
    if not key:
        raise RuntimeError("FMP_API_KEY 未配置")
    _fmp_pace()
    _fmp_tick()
    url = path_q if str(path_q).startswith("http") else (_fmp_base() + path_q)
    sep = "&" if "?" in url else "?"
    return _get(url + sep + "apikey=" + key)


def _fmp_quote_url(fam, sym):
    q = urllib.parse.quote(str(sym), safe="")
    if fam == "legacy":
        return _fmp_base() + "/quote/" + q
    return _FMP_STABLE_BASE + "/quote?symbol=" + q


def _fmp_history_url(fam, sym):
    q = urllib.parse.quote(str(sym), safe="")
    if fam == "legacy":
        return _fmp_base() + "/historical-price-full/%s?timeseries=280" % q
    return _FMP_STABLE_BASE + "/historical-price-eod/full?symbol=" + q


def _fmp_call_routed(kind, sym, url_fn):
    """kind='quote'|'history'。按 (kind:符号类) 路由:定版族直走;未定版按候选实弹
    探路,首个出数定版落盘;全候选失败 = 本班该类停用一次响亮(全部回包摘要进
    异常文本),同类其余票不再连环打 402。"""
    cls = _fmp_class(sym)
    rk = "%s:%s" % (kind, cls)
    route = _fmp_route_load()
    fam = route.get(rk)
    if fam == "":
        raise RuntimeError("fmp %s 类本班停用(探路全败)" % rk)
    fams = ([fam] if fam else []) + [f for f in ("legacy", "stable") if f != fam]
    errs = []
    for f in fams:
        try:
            data = json.loads(_fmp_get(url_fn(f, sym)))
            if data in (None, [], {}):
                errs.append("%s:空回包" % f)
                continue
            if isinstance(data, dict) and data.get("Error Message"):
                errs.append("%s:%s" % (f, str(data.get("Error Message"))[:100]))
                continue
            if route.get(rk) != f:
                route[rk] = f
                _fmp_route_save()
                print("[fetchers] fmp 路由定版 %s=%s" % (rk, f))
            return data
        except urllib.error.HTTPError as e:
            errs.append("%s:%s" % (f, _http_err_text(e)))
        except Exception as e:
            errs.append("%s:%s" % (f, str(e)[:120]))
    route[rk] = ""
    raise RuntimeError("fmp %s 全候选失败: %s" % (rk, " | ".join(errs)))


# ---- ThetaData 第二源(Lyra 拍板 2026-08-17:FMP + ThetaData,Alpaca backup)----
# 本地 Theta Terminal REST(默认 :25503 = 她机器实跑口,v3.24.3 起;env THETA_BASE 可覆盖)。key 由 Terminal 侧配置(option-workstation/
# theta/.env,Cursor 已填),请求本身零 key。Terminal 未起 = 每班探活一次失败 →
# 整链跳过,响亮记录不阻塞(铁则:不默认引入常驻依赖;起不起容器 Lyra 拍板)。
_THETA_STATE = {"up": None, "eod": None}  # eod: (path,param) 本班定版;"" = 探路全败本班停用
# 候选矩阵:v3 两种拼法×参数方言 + v2 + 无前缀。真相由 Terminal 回包定,不锁死守恒猜的档位。
_THETA_CANDS = [("/v3/stock/history/eod", "symbol")]
# v3.25.1:root 形参候选移除——v2 废弃(2026-08-19 戌实测:v3 只认 symbol,
# root 一律 410 deprecated;留着只在 symbol 失败时追加 410 噪音)。
_THETA_ROUTE_LOADED = [False]


def _theta_base():
    return os.getenv("THETA_BASE", "http://127.0.0.1:25503").rstrip("/")


def is_rth_now():
    """ET 09:30–16:00 且工作日。"""
    n = now_et()
    return n.weekday() < 5 and (n.hour, n.minute) >= (9, 30) and (n.hour, n.minute) < (16, 0)


def theta_atm_call_greeks(symbol, spot, min_dte=7, max_dte=30):
    """v3.29 F5:ATM 最近到期(min_dte–max_dte)call 的 greeks。端点按官方文档:
    GET {THETA_BASE}/v3/option/snapshot/greeks/all?symbol=X&expiration=*&right=call&strike_range=1&max_dte=N&format=json
    (Pro 档;盘外/收盘后快照为空——文档:market closed 当日返回无数据,午夜 ET 重置)。
    返回 {gamma, theta, implied_vol, dte, expiration, strike, mid} 或 None(缺=因子缺,由 factors 归一化;原因入 skip)。"""
    if not spot or spot <= 0:
        return None
    if not is_rth_now():
        _log_skip("theta_greeks", symbol, "盘外无快照(文档:closed 当日无数据)")
        return None
    if not _theta_up():
        _log_skip("theta_greeks", symbol, "Theta Terminal 未起")
        return None
    q = {"symbol": symbol, "expiration": "*", "right": "call", "strike_range": "1", "max_dte": str(max_dte), "format": "json"}
    url = _theta_base() + "/v3/option/snapshot/greeks/all?" + urllib.parse.urlencode(q)
    try:
        data = json.loads(_get(url))
    except Exception as e:
        _log_skip("theta_greeks", symbol, "greeks 请求失败:%s" % str(e)[:100])
        return None
    rows = data if isinstance(data, list) else (data.get("data") if isinstance(data, dict) else None)
    if not rows:
        _log_skip("theta_greeks", symbol, "greeks 空回包")
        return None
    today = trading_date()
    best = None
    for r in rows:
        try:
            exp = str(r.get("expiration") or "")
            exp_d = datetime.date.fromisoformat(exp) if "-" in exp else datetime.datetime.strptime(exp, "%Y%m%d").date()
            dte = (exp_d - today).days
            if dte < min_dte or dte > max_dte:
                continue
            strike = float(r.get("strike"))
            gamma, theta = r.get("gamma"), r.get("theta")
            if gamma is None or theta is None:
                continue
            key = (dte, abs(strike - float(spot)))
            if best is None or key < best[0]:
                bid, ask = float(r.get("bid") or 0), float(r.get("ask") or 0)
                best = (key, {"gamma": float(gamma), "theta": float(theta), "implied_vol": r.get("implied_vol"),
                              "dte": dte, "expiration": exp_d.isoformat(), "strike": strike,
                              "mid": (bid + ask) / 2 if (bid and ask) else None})
        except Exception:
            continue
    if best is None:
        _log_skip("theta_greeks", symbol, "无 %d–%d DTE 的 ATM call 行" % (min_dte, max_dte))
        return None
    return best[1]


def _theta_route_file():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), ".theta_route")


def _theta_route_load():
    """上班定过的版跨班续用(文件缓存);失效会自动回落矩阵重探,自愈 Terminal 升级。"""
    if _THETA_ROUTE_LOADED[0]:
        return
    _THETA_ROUTE_LOADED[0] = True
    try:
        j = json.load(open(_theta_route_file()))
        if j.get("path") and j.get("param"):
            _THETA_STATE["eod"] = (str(j["path"]), str(j["param"]))
    except Exception:
        pass


def _theta_route_save(path, param):
    try:
        with open(_theta_route_file(), "w") as f:
            json.dump({"path": path, "param": param,
                       "saved": datetime.datetime.now().astimezone().isoformat()}, f)
    except Exception:
        pass


def _theta_up():
    if _THETA_STATE["up"] is not None:
        return _THETA_STATE["up"]
    try:
        req = urllib.request.Request(_theta_base() + "/v2/system/mdds/status", headers=UA)
        with urllib.request.urlopen(req, timeout=3):
            _THETA_STATE["up"] = True
    except urllib.error.HTTPError:
        # 任何 HTTP 状态码(含新版 Terminal 对旧状态口回的 410)都证明进程活着——
        # 探活只判"在不在",不判语义(8-17:410 曾被误判未起,整链被冤枉跳过)
        _THETA_STATE["up"] = True
    except Exception:
        _THETA_STATE["up"] = False
    if not _THETA_STATE["up"]:
        print("[fetchers] Theta Terminal(%s)未起——本班第二源跳过(FMP→Alpaca 直连)" % _theta_base())
    return _THETA_STATE["up"]


def _theta_rows_v2(header, resp):
    """Theta v2 表格式回包(header.format + response 行)→ 升序 rows。"""
    fmt = [str(x).lower() for x in (header or {}).get("format") or []]
    idx = {k: (fmt.index(k) if k in fmt else None)
           for k in ("date", "open", "high", "low", "close", "volume")}
    if any(idx[k] is None for k in ("date", "open", "high", "low", "close")):
        return []
    rows = []
    for r in resp or []:
        try:
            d8 = str(r[idx["date"]])
            rows.append({"date": "%s-%s-%s" % (d8[:4], d8[4:6], d8[6:8]),
                         "o": float(r[idx["open"]]), "h": float(r[idx["high"]]),
                         "l": float(r[idx["low"]]), "c": float(r[idx["close"]]),
                         "v": ((float(r[idx["volume"]]) or None)
                               if idx["volume"] is not None else None)})
        except (TypeError, ValueError, IndexError):
            continue
    rows.sort(key=lambda x: x["date"])
    return rows


def _theta_norm_date(x):
    s = str(x)
    if re.fullmatch(r"\d{8}", s):
        return "%s-%s-%s" % (s[:4], s[4:6], s[6:8])
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", s):
        return s[:10]
    return None


def _theta_rows_any(text):
    """回包体裁自适应:v2 表格式 JSON / dict 列表 JSON / CSV——三种都认,
    认不出即 [](上游响亮记录)。v3 体裁不猜死,首个能解析出数的定版。"""
    t = (text or "").strip()
    if not t:
        return []
    if t[0] in "{[":
        try:
            data = json.loads(t)
        except ValueError:
            return []
        if isinstance(data, dict):
            if "header" in data and "response" in data:
                return _theta_rows_v2(data.get("header"), data.get("response"))
            for k in ("response", "data", "results", "rows"):
                if isinstance(data.get(k), list):
                    data = data[k]
                    break
        if isinstance(data, list) and data and isinstance(data[0], dict):
            rows = []
            for r in data:
                low = {str(k).lower(): v for k, v in r.items()}
                d = _theta_norm_date(low.get("date") or low.get("day") or low.get("timestamp") or "")
                try:
                    if d and low.get("close") is not None:
                        rows.append({"date": d, "o": float(low.get("open") or 0) or None,
                                     "h": float(low.get("high") or 0) or None,
                                     "l": float(low.get("low") or 0) or None,
                                     "c": float(low["close"]),
                                     "v": (float(low["volume"]) if low.get("volume") not in (None, "") else None)})
                except (TypeError, ValueError):
                    continue
            rows.sort(key=lambda x: x["date"])
            return rows
        return []
    # CSV:首行含 date+close 才认
    lines = [ln for ln in t.splitlines() if ln.strip()]
    if len(lines) >= 2 and "date" in lines[0].lower() and "close" in lines[0].lower():
        hdr = [h.strip().lower() for h in lines[0].split(",")]
        col = {k: (hdr.index(k) if k in hdr else None)
               for k in ("date", "open", "high", "low", "close", "volume")}
        if col["date"] is None or col["close"] is None:
            return []
        rows = []
        for ln in lines[1:]:
            cs = ln.split(",")
            try:
                d = _theta_norm_date(cs[col["date"]])
                if not d:
                    continue
                def _f(k):
                    i = col[k]
                    return float(cs[i]) if (i is not None and i < len(cs) and cs[i].strip()) else None
                c = _f("close")
                if c is None:
                    continue
                rows.append({"date": d, "o": _f("open"), "h": _f("high"),
                             "l": _f("low"), "c": c, "v": _f("volume")})
            except (TypeError, ValueError, IndexError):
                continue
        rows.sort(key=lambda x: x["date"])
        return rows
    return []


def _theta_mine_paths(head):
    """从 410/404 弃用告示正文里挖新路径提示(告示通常写明改用哪条)。"""
    return [p.rstrip(".,;:)\"'") for p in re.findall(r"/v\d[\w/\-\.]*", head or "")]


def _theta_history(sym):
    """第二源:Theta Terminal 股票/ETF EOD(指数 ^ 符号不走此端点→[])。
    路径自发现:候选矩阵逐一实弹,首个出数的(路径,参数)定版并落盘 .theta_route
    跨班续用;全败=本班停用一次响亮(全部回包头进日志),不产生人肉取证往返。"""
    s = str(sym).upper()
    if (s.startswith("^") or s in ("CLUSD", "GCUSD")
            or not re.fullmatch(r"[A-Z]{1,5}", s or "") or not _theta_up()):
        return []
    _theta_route_load()
    if _THETA_STATE["eod"] == "":
        return []
    end = trading_date()
    start = end - datetime.timedelta(days=430)
    # v3 上限 365 天/请求(8-17 实弹 400: max 365 days)→ ≤360 天分窗,最新窗在前:
    # 探路在最新窗上做;新窗失败=数据陈旧按失败处理,旧窗尽力补(缺了只伤 52w 边缘)
    chunks, ce = [], end
    while ce >= start:
        cs = max(start, ce - datetime.timedelta(days=360))
        chunks.append((cs, ce))
        ce = cs - datetime.timedelta(days=1)
    d1, d2 = chunks[0]
    dates = "&start_date=%s&end_date=%s" % (d1.strftime("%Y%m%d"), d2.strftime("%Y%m%d"))
    if _THETA_STATE["eod"]:
        cands = [_THETA_STATE["eod"]] + [c for c in _THETA_CANDS if c != _THETA_STATE["eod"]]
    else:
        cands = list(_THETA_CANDS)
    locked = bool(_THETA_STATE["eod"])
    errs, tried = [], set()
    i = 0
    while i < len(cands):
        path, param = cands[i]
        i += 1
        if (path, param) in tried:
            continue
        tried.add((path, param))
        url = "%s%s?%s=%s%s" % (_theta_base(), path, param, s, dates)
        try:
            text = _get(url)
        except urllib.error.HTTPError as e:
            try:
                head = e.read()[:400].decode("utf-8", "replace")
            except Exception:
                head = ""
            errs.append("%s?%s= HTTP %s %s" % (path, param, e.code, head[:120]))
            for mined in _theta_mine_paths(head):
                for pm in ("symbol", "root"):
                    if (mined, pm) not in tried:
                        cands.append((mined, pm))
            if locked:  # 定版路径失效(Terminal 升级)→ 解锁回落全矩阵重探自愈
                locked = False
            continue
        except Exception as e:
            errs.append("%s?%s= %s" % (path, param, str(e)[:100]))
            if locked:
                locked = False
            continue
        rows = _theta_rows_any(text)
        if rows:
            if _THETA_STATE["eod"] != (path, param):
                _THETA_STATE["eod"] = (path, param)
                _theta_route_save(path, param)
                print("[fetchers] Theta EOD 路径定版: %s (参数 %s=) → .theta_route" % (path, param))
            for c1, c2 in chunks[1:]:  # 旧窗尽力补齐(本地 Terminal 零成本)
                try:
                    more = _theta_rows_any(_get(
                        "%s%s?%s=%s&start_date=%s&end_date=%s"
                        % (_theta_base(), path, param, s,
                           c1.strftime("%Y%m%d"), c2.strftime("%Y%m%d"))))
                except Exception as e:
                    more = []
                    _log_skip("theta.history.chunk", s,
                              "%s..%s %s" % (c1, c2, str(e)[:100]))
                rows.extend(more)
            merged = {r["date"]: r for r in rows}
            return sorted(merged.values(), key=lambda x: x["date"])
        errs.append("%s?%s= empty/drift: %s" % (path, param, str(text)[:100]))
        if locked:
            locked = False
    # 全败:本班停用(不再为每票烧一轮矩阵),证据全量进日志、摘要进 skips
    _THETA_STATE["eod"] = ""
    print("[fetchers] Theta EOD 探路全败,本班第二源停用。实弹回执:")
    for e in errs:
        print("  ·", e)
    _log_skip("theta.history", s, " | ".join(errs))
    return []


def _cache_path(sym):
    safe = str(sym).upper().replace("^", "IDX_").replace("/", "_").replace("\\", "_")
    return os.path.join(PRICES_DIR, safe + ".json")


def _cache_load(sym, key=None):
    """→ (rows, src)。新格式 {src, rows};旧格式裸列表按 src=unknown 兼容读。"""
    try:
        doc = json.load(open(_cache_path(key or sym), encoding="utf-8"))
        if isinstance(doc, dict) and "rows" in doc:
            return (doc.get("rows") or []), str(doc.get("src") or "unknown")
        return (doc if isinstance(doc, list) else []), "unknown"
    except Exception:
        return [], ""


def _cache_save(sym, rows, src="fmp", proxy=None):
    """缓存带血统(v3.24.5 指数缓存污染根修):src 入盘;代理序列(指数走 ETF 代理)
    写独立键 SYM__proxy_XXX,读路径禁跨序列——8-17 案里 SPY 序列混进 ^GSPC 主键,
    FMP 恢复后缓存仍"新鲜"不刷新,chg_pct 跨序列算出 897% 级异常。"""
    key = ("%s__proxy_%s" % (sym, proxy)) if proxy else sym
    try:
        os.makedirs(PRICES_DIR, exist_ok=True)
        json.dump({"src": src, "rows": rows[-320:]},
                  open(_cache_path(key), "w", encoding="utf-8"))
    except Exception as e:
        _log_skip("quote_layer.cache", sym, e)


def _fmp_history(sym):
    """FMP 日线历史 → 升序 [{date,o,h,l,c,v}]。经路由器(legacy/stable 自探定版);
    legacy 回 {historical:[...倒序]},stable 回裸列表——双形状都吃,统一排升序。"""
    try:
        data = _fmp_call_routed("history", sym, _fmp_history_url)
    except Exception as e:
        _log_skip("fmp.history", sym, e)
        return []
    hist = data.get("historical") if isinstance(data, dict) else data
    rows = []
    for h in (hist or []):
        try:
            rows.append({"date": str(h["date"])[:10],
                         "o": float(h["open"]), "h": float(h["high"]),
                         "l": float(h["low"]), "c": float(h["close"]),
                         "v": (float(h.get("volume") or 0) or None)})
        except (KeyError, TypeError, ValueError):
            continue
    rows.sort(key=lambda r: r["date"])
    return rows


_ALPACA_KEY_NAMES = ("ALPACA_KEY_ID", "ALPACA_API_KEY", "APCA_API_KEY_ID")
_ALPACA_SEC_NAMES = ("ALPACA_SECRET_KEY", "APCA_API_SECRET_KEY")
# 指数在 backup 侧只能走 ETF 代理(Alpaca 无指数/期货);触发即在 source 标注
_ALPACA_INDEX_PROXY = {"^GSPC": "SPY", "^IXIC": "QQQ", "^VIX": "VIXY"}


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


def _alpaca_history(sym):
    """backup 腿:Alpaca 日线 OHLCV → (升序 rows, proxy)。指数走 ETF 代理并标注。"""
    key, sec = _load_alpaca_keys()
    s = str(sym).upper()
    proxy = None
    if s.startswith("^"):
        proxy = _ALPACA_INDEX_PROXY.get(s)
        if not proxy:
            return [], None
        s = proxy
    if not (key and sec) or not re.fullmatch(r"[A-Z]{1,5}", s or ""):
        return [], proxy
    start = (trading_date() - datetime.timedelta(days=430)).isoformat() + "T00:00:00Z"
    # 必须 sort=desc:asc+start+limit 会吃到最旧 N 根(与 alpha daily_bars 同坑)
    url = ("https://data.alpaca.markets/v2/stocks/%s/bars"
           "?timeframe=1Day&start=%s&limit=320&adjustment=raw&feed=%s&sort=desc"
           % (s, start, alpaca_feed()))
    req = urllib.request.Request(
        url, headers={**UA, "APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_context()) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        _log_skip("alpaca.history", s, e)
        return [], proxy
    rows = []
    for b in reversed(data.get("bars") or []):
        try:
            rows.append({"date": str(b["t"])[:10],
                         "o": float(b["o"]), "h": float(b["h"]),
                         "l": float(b["l"]), "c": float(b["c"]),
                         "v": (float(b.get("v") or 0) or None)})
        except (KeyError, TypeError, ValueError):
            continue
    return rows, proxy


def _alpaca_live(symbols):
    """backup 腿:Alpaca 批量 snapshot → {SYM: live_row}(FMP quote 缺席票用)。
    现场 0817 版 snapshot 端点收编;含盘后 latestTrade/latestQuote 字段。"""
    key, sec = _load_alpaca_keys()
    syms = [str(s).upper() for s in (symbols or []) if s]
    syms = [(_ALPACA_INDEX_PROXY.get(s, s), s) for s in syms]
    real = sorted({r for r, _ in syms if re.fullmatch(r"[A-Z]{1,5}", r)})
    if not (key and sec) or not real:
        return {}
    out = {}
    for i in range(0, len(real), 40):
        chunk = real[i:i + 40]
        url = ("https://data.alpaca.markets/v2/stocks/snapshots?symbols="
               + ",".join(chunk))
        req = urllib.request.Request(
            url, headers={**UA, "APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_context()) as r:
                data = json.loads(r.read().decode())
        except Exception as e:
            _log_skip("quote_layer.alpaca_live", ",".join(chunk[:3]), e)
            continue
        for rsym in chunk:
            snap = data.get(rsym) or {}
            bar = snap.get("dailyBar") or snap.get("prevDailyBar") or {}
            prev = snap.get("prevDailyBar") or {}
            try:
                row = {"date": str(bar.get("t") or "")[:10],
                       "o": float(bar["o"]), "h": float(bar["h"]),
                       "l": float(bar["l"]), "c": float(bar["c"]),
                       "v": (float(bar.get("v") or 0) or None),
                       "prev_close_live": (float(prev["c"]) if prev.get("c") is not None else None),
                       "_src": "alpaca"}
            except (KeyError, TypeError, ValueError):
                continue
            for want, orig in syms:
                if want == rsym:
                    out[orig] = dict(row, _proxy=(rsym if orig != rsym else None))
    return out


def _fmp_quote(symbols):
    """FMP quote → {SYM: 行}。按符号类路由(stock/index/commodity 各自定版端点):
    stock 类定版 legacy 时保留批量;其余单票走路由;类级探路全败一次响亮,
    同类其余票不再连环(V6 案:指数/商品 402 连环刷 skips 的根修)。"""
    global _FMP_BATCH_OK
    out = {}
    syms = [str(s).upper() for s in (symbols or []) if s]
    if not syms or not _fmp_key():
        return out

    def eat(data):
        for r in (data if isinstance(data, list) else [data]):
            if isinstance(r, dict):
                s = str(r.get("symbol") or "").upper()
                if s:
                    out[s] = r

    by_cls = {}
    for s in syms:
        by_cls.setdefault(_fmp_class(s), []).append(s)
    st = by_cls.pop("stock", [])
    if st:
        fam = _fmp_route_load().get("quote:stock")
        if fam in (None, "legacy") and _FMP_BATCH_OK and len(st) > 1:
            try:
                for i in range(0, len(st), 50):
                    eat(json.loads(_fmp_get("/quote/" + urllib.parse.quote(",".join(st[i:i + 50]), safe=","))))
                if _fmp_route_load().get("quote:stock") != "legacy":
                    _FMP_ROUTE["quote:stock"] = "legacy"
                    _fmp_route_save()
                st = []
            except Exception as e:
                _FMP_BATCH_OK = False
                msg = _http_err_text(e) if isinstance(e, urllib.error.HTTPError) else str(e)
                _log_skip("fmp.quote_batch", ",".join(syms[:3]), "批量被拒,退单票: %s" % msg)
        for s in st:
            try:
                eat(_fmp_call_routed("quote", s, _fmp_quote_url))
            except RuntimeError as e:
                _log_skip("fmp.quote", s, e)
                if "本班停用" in str(e) and "全候选失败" not in str(e):
                    break
            except Exception as e:
                _log_skip("fmp.quote", s, e)
    for cls, group in by_cls.items():
        for s in group:
            try:
                eat(_fmp_call_routed("quote", s, _fmp_quote_url))
            except RuntimeError as e:
                _log_skip("fmp.quote", s, e)
                if "本班停用" in str(e) and "全候选失败" not in str(e):
                    break
            except Exception as e:
                _log_skip("fmp.quote", s, e)
    return out


def _live_row_from_fmp(q):
    """FMP quote 行 → 今日 bar(缺 O/H/L 用现价补,如实反映盘初形态未成)。"""
    try:
        c = float(q.get("price"))
    except (TypeError, ValueError):
        return None
    def f(k):
        try:
            v = float(q.get(k))
            return v if v > 0 else None
        except (TypeError, ValueError):
            return None
    ts = q.get("timestamp")
    day = ""
    try:
        dt = datetime.datetime.fromtimestamp(int(ts), tz=datetime.timezone.utc)
        day = (dt.astimezone(_ET).date() if _ET else dt.date()).isoformat()
    except (TypeError, ValueError, OSError):
        day = trading_date().isoformat()
    return {"date": day, "o": f("open") or c, "h": f("dayHigh") or c,
            "l": f("dayLow") or c, "c": c,
            "v": f("volume"), "prev_close_live": f("previousClose"), "_src": "fmp",
            "mcap": f("marketCap")}   # v3.26:市值随行(legacy/stable /quote 均有该字段)


def _merge_live(rows, live):
    if not live:
        return rows
    if rows and rows[-1]["date"] == live["date"]:
        return rows[:-1] + [live]
    if not rows or live["date"] > rows[-1]["date"]:
        return rows + [live]
    return rows


def now_et():
    """ET 当前时刻(与 trading_date 同一时钟源;测试可覆盖)。"""
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-4)))


def _history(sym, need_date=None):
    """历史日线唯一入口:缓存(新鲜且主源血统)→ FMP → Theta(仅 stock 类)→
    Alpaca backup(代理序列独立键)→ 代理/陈旧缓存(响亮)→ []。
    backup 血统的新鲜缓存每班先试一次主源升级(新鲜度按来源分级)。"""
    cls = _fmp_class(sym)
    rows, src_ = _cache_load(sym)
    need = need_date or prev_trading_day(trading_date()).isoformat()
    fresh = bool(rows) and rows[-1].get("date", "") >= need
    backup_blood = src_.startswith(("alpaca", "theta"))
    if fresh and not (backup_blood and _fmp_key() and sym not in _FMP_UPGRADE_TRIED):
        return rows, "cache"
    if _fmp_key():
        _FMP_UPGRADE_TRIED.add(sym)
        fresh_rows = _fmp_history(sym)
        if fresh_rows:
            _cache_save(sym, fresh_rows, "fmp")
            return fresh_rows, "fmp"
        if fresh:
            return rows, "cache"
    if cls == "stock":
        th = _theta_history(sym)
        if th:
            _cache_save(sym, th, "theta")
            return th, "theta"
    if cls != "commodity":   # Alpaca 无商品
        ab, proxy = _alpaca_history(sym)
        if ab:
            _cache_save(sym, ab, "alpaca", proxy=proxy)
            if proxy:
                return ab, "alpaca:%s" % proxy
            return ab, "alpaca"
    if rows:
        print("[fetchers] %s 全源失败,退陈旧缓存(至 %s,血统 %s)" % (sym, rows[-1].get("date"), src_ or "unknown"))
        return rows, "cache-stale:%s" % (src_ or "unknown")
    if cls == "index":
        proxy = _ALPACA_INDEX_PROXY.get(sym)
        if proxy:
            prows, _psrc = _cache_load(sym, key="%s__proxy_%s" % (sym, proxy))
            if prows:
                print("[fetchers] %s 全源失败,退 %s 代理缓存(独立键,如实标注)" % (sym, proxy))
                return prows, "cache-proxy:%s" % proxy
    return [], "none"


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


def _tape_from_ohlc(o, h, l, c, pc):
    close_loc = round((c - l) / (h - l), 2) if h > l else None
    chg_pct = round((c / pc - 1) * 100, 2) if pc else None
    tape = ""
    if pc is not None and close_loc is not None:
        tape = ("冲高回落" if (h > pc and close_loc < 0.4)
                else ("强势收高" if close_loc > 0.8 and c > pc else ""))
    return close_loc, chg_pct, tape


def _derive(name, rows, source_label):
    """升序日线 → 引擎全字段读数(v3.19-3.22 全员:Alpaca 过渡层曾静默丢
    vol_x20/on20/in20/_rets20,此处整族复活;公式与 v3.23 引擎逐字一致)。"""
    if len(rows) < 2:
        return None
    opens = [r["o"] for r in rows]
    closes = [r["c"] for r in rows]
    vols = [r.get("v") for r in rows]
    last, prev = rows[-1], rows[-2]
    o, h, l, c = last["o"], last["h"], last["l"], last["c"]
    pc = prev["c"]
    close_loc, chg_pct, tape = _tape_from_ohlc(o, h, l, c, pc)
    day = last.get("date") or ""
    d = {"name": name, "ticker": name, "date": day, "Date": day,
         "open": o, "high": h, "low": l, "close": c, "Close": str(round(c, 4)),
         "chg_pct": chg_pct,
         "chg5_pct": round((c / closes[-6] - 1) * 100, 2) if len(closes) >= 6 else None,
         "mom20_pct": round((c / closes[-21] - 1) * 100, 2) if len(closes) >= 21 else None,
         "high52_dist_pct": round((c / max(closes) - 1) * 100, 2) if closes else None,
         "rsi14": _rsi14(closes),
         # ④隔夜/日内 20 日分解:T+0 纯日内结构必须直面的读数
         "on20_pct": (round(sum(opens[i] / closes[i - 1] - 1
                                for i in range(len(closes) - 20, len(closes))) * 100, 2)
                      if len(closes) >= 21 else None),
         "in20_pct": (round(sum(closes[i] / opens[i] - 1
                                for i in range(len(closes) - 20, len(closes))) * 100, 2)
                      if len(closes) >= 21 else None),
         # ①量比:末根量 / 前20日均量(放量的实测定义)
         "vol_x20": (round(vols[-1] / (sum(v for v in vols[-21:-1] if v) /
                                       max(1, len([v for v in vols[-21:-1] if v]))), 2)
                     if vols and vols[-1] and any(vols[-21:-1]) else None),
         # ②相关性收敛的原料:末20日收益序列(引擎内用;prompt 侧由 _slim_raw 剥除)
         "_rets20": ([round(closes[i] / closes[i - 1] - 1, 4)
                      for i in range(len(closes) - 20, len(closes))]
                     if len(closes) >= 21 else None),
         # v3.26 质量地板实测基:价格=末根收盘;20 日平均成交额=前 20 根 close×volume 均值
         # (末根为当日/盘中未收盘 bar,不计;样本 <5 根 = 无实测,None 不装数);市值随 live 行
         "price": c,
         "last_bar_date": rows[-1].get("date"),   # v3.28.2:末根日期(趋势榜覆盖率自证用)
         "dist_high20_pct": (round((c / max(r["h"] for r in rows[-20:]) - 1) * 100, 2) if len(rows) >= 5 and max(r["h"] for r in rows[-20:]) else None),   # v3.29 F2
         # v3.28 趋势读数:最近 5 根中收涨根数(对前一根)、10 日涨幅
         "up5": sum(1 for i in range(max(1, len(rows) - 5), len(rows)) if rows[i]["c"] > rows[i - 1]["c"]) if len(rows) >= 2 else None,
         "chg10_pct": (round((c / rows[-11]["c"] - 1) * 100, 2) if len(rows) >= 11 and rows[-11]["c"] else None),
         "adv20_usd": (round(sum(r["c"] * r["v"] for r in rows[-21:-1] if r.get("v") and r.get("c"))
                             / len([r for r in rows[-21:-1] if r.get("v") and r.get("c")]))
                       if len([r for r in rows[-21:-1] if r.get("v") and r.get("c")]) >= 5 else None),
         "adv20_days": len([r for r in rows[-21:-1] if r.get("v") and r.get("c")]),
         "mcap_b": (round(last["mcap"] / 1e9, 2) if last.get("mcap") else None),
         "close_loc": close_loc, "source": source_label,
         "feed": alpaca_feed(), "feed_label": feed_ah_label()}
    d["tape_flag"] = tape or ""
    if ":" in (source_label or ""):
        d["proxy"] = source_label.split(":", 1)[1]
    return d


def quote_layer_snapshot(symbols, *, with_rsi=True):
    """快照缝 v3.24:FMP 批量 quote + 缓存历史 → 全字段读数;
    FMP 缺席票逐票落 Alpaca backup;双失败响亮入 skip,不装数。
    with_rsi=False:跳过历史(全宇宙扫描防拖死),仅出 quote 核心字段。
    换更好的数据 API 只换本函数与 _history 内脏——爬虫/引擎/渲染零改动。"""
    syms = [str(s).upper() for s in (symbols or []) if s]
    out = {}
    todo = [s for s in syms if s not in _QUOTE_MEMO]
    quotes = _fmp_quote(todo)
    missing_live = [s for s in todo if s not in quotes]
    alp_live = _alpaca_live(missing_live) if missing_live else {}
    for sym in syms:
        if sym in _QUOTE_MEMO:
            out[sym] = dict(_QUOTE_MEMO[sym])
            continue
        live = None
        src = "fmp"
        if sym in quotes:
            live = _live_row_from_fmp(quotes[sym])
        if live is None and sym in alp_live:
            live = alp_live[sym]
            src = "alpaca:%s" % live["_proxy"] if live.get("_proxy") else "alpaca"
        rows, hist_src = _history(sym) if with_rsi else ([], "quote-only")
        rows = _merge_live(list(rows), live)
        if len(rows) < 2 and live and live.get("prev_close_live"):
            pcl = live["prev_close_live"]
            rows = [{"date": "", "o": pcl, "h": pcl, "l": pcl, "c": pcl, "v": None}, live]
        label = src if live is not None else hist_src
        d = _derive(sym, rows, label)
        if d is None:
            _log_skip("quote_layer", sym, "FMP+Alpaca 双失败,无缓存")
            continue
        _QUOTE_MEMO[sym] = dict(d)
        out[sym] = d
    return out


def history_snapshot(symbols, need_date=None):
    """v3.28:只用缓存/历史日线出读数(不打 quote、不进 _QUOTE_MEMO)——全宇宙趋势扫描用,
    末根=最近一根已收盘日线;need_date=缓存最新 bar 须 ≥ 此日期否则重拉(晚班要当日终盘)。"""
    out = {}
    for sym in [str(s).upper() for s in (symbols or []) if s]:
        rows, hist_src = _history(sym, need_date=need_date)
        d = _derive(sym, list(rows), hist_src)
        if d is None:
            continue
        out[sym] = d
    return out


def fetch_screener_universe(cache_path=None, ttl_s=20 * 3600):
    """v3.28(BMNR 案:FMP 涨幅榜按单日 % 排、最活跃榜按股数排,连涨一周 +35% 的 $1B/日大票两榜都进不了):
    全市场普通股宇宙,FMP stable /company-screener 一次调用(她档位 8-25 实测 200 键齐),日缓存。
    定义:非 ETF/基金、在交易、NYSE/NASDAQ/AMEX、price≥POOL_PRICE_FLOOR、当日 price×volume≥5e7(粗地板,
    精地板 adv20≥POOL_ADV_FLOOR_USD 在快照后算)。返回 [symbol],失败返 [] 并入 skip(不装数)。"""
    cache_path = cache_path or os.path.join(os.path.dirname(PRICES_DIR), "state", "universe_screener.json")
    try:
        doc = json.load(open(cache_path, encoding="utf-8"))
        if time.time() - float(doc.get("ts", 0)) < ttl_s and doc.get("symbols"):
            return list(doc["symbols"])
    except Exception:
        pass
    key = _fmp_key()
    if not key:
        _log_skip("screener_universe", "-", "无 FMP key")
        return []
    pf = pool_price_floor()
    q = {"limit": 10000, "isEtf": "false", "isFund": "false", "isActivelyTrading": "true",
         "priceMoreThan": int(pf), "exchange": "NYSE,NASDAQ,AMEX", "apikey": key}
    url = _FMP_STABLE_BASE + "/company-screener?" + urllib.parse.urlencode(q)
    try:
        _fmp_tick()
        rows = json.loads(_get(url))
    except Exception as e:
        _log_skip("screener_universe", "-", "screener 失败:%s" % str(e)[:120])
        return []
    if not isinstance(rows, list) or len(rows) < 500:
        _log_skip("screener_universe", "-", "screener 回包异常/截断 n=%s" % (len(rows) if isinstance(rows, list) else "?"))
        return []
    syms, seen, vol0 = [], set(), 0
    for r in rows:
        try:
            sym = str(r.get("symbol") or "").upper()
            if not re.fullmatch(r"[A-Z]{1,5}", sym) or sym in seen:
                continue
            if r.get("isEtf") or r.get("isFund") or r.get("isActivelyTrading") is False:
                continue
            if str(r.get("exchangeShortName") or "").upper() not in ("NYSE", "NASDAQ", "AMEX"):
                continue
            px, vol = float(r.get("price") or 0), float(r.get("volume") or 0)
            if px < pf:
                continue
            # v3.28.1(戌 8-25 现场抓:screener 回 BMNR volume=0,粗筛 price×volume 把它误杀——这版就是为它建的):
            # volume 为 0/缺 = 该字段不可信,放行,交给 history_snapshot 的 adv20 精地板(那才是实测)
            if vol > 0 and px * vol < 5e7:
                continue
            if vol <= 0:
                vol0 += 1
            seen.add(sym); syms.append(sym)
        except Exception:
            continue
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        json.dump({"ts": time.time(), "n": len(syms), "raw_n": len(rows), "volume0_passed": vol0, "symbols": syms},
                  open(cache_path, "w", encoding="utf-8"))
        print("[fetchers] screener 宇宙 %d/%d(volume=0 放行 %d 票,由 adv20 精地板定)" % (len(syms), len(rows), vol0))
    except Exception:
        pass
    return syms


def quote_layer_bars(symbol, limit=260):
    """个股日线收盘缝(FMP 主源→Alpaca backup,经缓存)。换 API 只改 _history 内脏。"""
    rows, _src = _history(str(symbol or "").upper())
    return [r["c"] for r in rows][-max(int(limit or 260), 15):]


class quote_layer:
    """v3.16§⑦ 换源唯一缝:snapshot(syms) / bars(sym)。v3.24 内脏 = FMP 主 + Alpaca backup。"""
    snapshot = staticmethod(quote_layer_snapshot)
    bars = staticmethod(quote_layer_bars)


def alpaca_snapshots(symbols):
    """兼容旧名 → quote_layer.snapshot(v3.16§⑦ 缝;内脏已换 FMP 主源)。"""
    return quote_layer.snapshot(symbols)


def alpaca_daily_closes(symbols, limit=260):
    """兼容旧名 → quote_layer.bars 批量。"""
    out = {}
    for sym in [str(s).upper() for s in (symbols or []) if s]:
        seq = quote_layer.bars(sym, limit=limit)
        if len(seq) >= 15:
            out[sym] = seq
        elif seq:
            _log_skip("quote_layer.bars", sym, "closes=%d(<15, RSI null)" % len(seq))
    return out


def data_plane_banner():
    """启动横幅:当班数据源实况。stooq 已移除,不回退。"""
    ak, asec = _load_alpaca_keys()
    alp = "在位" if (ak and asec) else "未配置"
    if _fmp_key():
        return ("FMP 主源(预算 %d/日,当日已用 %d)· Theta 第二源=%s · Alpaca backup=%s · %s · stooq 已移除"
                % (int(os.getenv("FMP_DAILY_BUDGET", "250")), fmp_calls_today(), "在线" if _theta_up() else "未起(跳过)", alp, feed_ah_label()))
    if ak and asec:
        return "⚠ FMP_API_KEY 未配置——本班全线退 Alpaca backup(指数=ETF 代理);请补 .env"
    return "⚠ FMP 与 Alpaca 均未配置——tape 全线无主路径(stooq 已移除,不回退)"


# ---- 符号映射(引擎 _stooq_daily 兼容缝 + 指数真符号回岗) ----
_INDEX_MAP = {"^spx": "^GSPC", "^ndq": "^IXIC", "^vix": "^VIX", "rsp.us": "RSP",
              "hyg.us": "HYG", "lqd.us": "LQD"}


def _sym_map(sym, name=""):
    """stooq 形符号 → quote_layer 符号。pltr.us→PLTR;指数→FMP 真指数符号。"""
    s = (sym or "").strip().lower()
    if s in _INDEX_MAP:
        return _INDEX_MAP[s]
    if s.endswith(".us"):
        return s[:-3].upper()
    if s.startswith("^"):
        return s.upper()
    if re.fullmatch(r"[A-Za-z]{1,5}", s or ""):
        return s.upper()
    n = (name or "").strip().upper()
    if re.fullmatch(r"[A-Z]{1,5}", n):
        return n
    return None


def _stooq_daily(sym, name, skip_src):
    """兼容缝:引擎原 stooq 日线调用 → quote_layer(FMP 主源)。字段对齐引擎全员。"""
    ticker = _sym_map(sym, name)
    if not ticker:
        _log_skip(skip_src, sym or name, "no ticker map")
        return None
    snaps = quote_layer_snapshot([ticker], with_rsi=True)
    it = snaps.get(ticker)
    if not it:
        _log_skip(skip_src, ticker, "quote_layer miss(FMP+Alpaca)")
        return None
    d = dict(it)
    d["name"] = name or ticker
    return d


# ============================================================================
# 十二爬虫(tape 走 quote_layer;事件/日历/盘后/流动性 = Nasdaq/官方零 key 端点不动)
# ============================================================================

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


def fetch_commodities():
    """油/金:FMP 商品端点主源(CLUSD≈WTI 期货连续 / GCUSD≈COMEX 金)——真商品回岗;
    免费档若拒符号 → USO/GLD ETF 代理并在 note/proxy 明标(不装现货)。stooq 已移除。"""
    def go():
        plan = (("WTI", "CLUSD", "USO", "USO ETF proxy for WTI crude env — not CL futures"),
                ("GOLD", "GCUSD", "GLD", "GLD ETF proxy for gold env — not XAU spot"))
        out = []
        for name, fsym, psym, pnote in plan:
            snaps = quote_layer_snapshot([fsym]) if _fmp_key() else {}
            it = snaps.get(fsym)
            if it and it.get("chg_pct") is not None:
                d = dict(it); d["name"] = name; d["proxy"] = fsym
                out.append(d)
                continue
            snaps = quote_layer_snapshot([psym])
            it = snaps.get(psym)
            if it:
                d = dict(it); d["name"] = name; d["proxy"] = psym; d["note"] = pnote
                out.append(d)
            else:
                _log_skip("commodities", fsym, "FMP 商品+ETF 代理双失败")
        return out
    return _wrap("commodities", go)


_INDEX_PLAN = (("SP500", "^GSPC"), ("NASDAQ", "^IXIC"), ("VIX", "^VIX"),
               ("RSP", "RSP"), ("HYG", "HYG"), ("LQD", "LQD"))


def fetch_indices():
    """爬虫#3:真指数(FMP ^GSPC/^IXIC/^VIX)+ RSP 广度 + HYG/LQD 信用金丝雀。
    链=quote_layer(FMP 主/Theta/Alpaca backup),Yahoo 兜底已摘除(Lyra 2026-08-17:
    质量差不用,FMP 付费档全接)。三大指数缺任一=响亮 skip+横幅降级,不找替身。"""
    def go():
        snaps = quote_layer_snapshot([sym for _, sym in _INDEX_PLAN])
        out = []
        for name, sym in _INDEX_PLAN:
            it = snaps.get(sym)
            if it:
                d = dict(it); d["name"] = name
                out.append(d)
            else:
                _log_skip("indices", sym, "quote_layer miss(Yahoo 已摘除,无兜底)")
        have = {x["name"] for x in out}
        missing = [n for n in ("SP500", "NASDAQ", "VIX") if n not in have]
        if missing:
            print("[fetchers] ⚠ 指数缺口 %s——FMP/Alpaca 双失,本班降级如实呈现" % ",".join(missing))
        return out
    return _wrap("indices", go)


# v3.6 累加:对冲腿 + 资金迁徙目的地(cls=hedge|rotation)
_HEDGE_PLAN = (
    ("GLD", "hedge"), ("SLV", "hedge"), ("OXY", "hedge"), ("USO", "hedge"),
    ("TLT", "hedge"), ("UUP", "hedge"),
    ("FXI", "rotation"), ("KWEB", "rotation"), ("EWZ", "rotation"),
    ("EWJ", "rotation"), ("EEM", "rotation"), ("BABA", "rotation"),
)


def fetch_hedge_assets():
    """爬虫#8:对冲+迁徙资产——quote_layer 唯一路径(FMP 主/Alpaca backup)。"""
    def go():
        snaps = quote_layer_snapshot([s for s, _ in _HEDGE_PLAN])
        out = []
        for sym, cls in _HEDGE_PLAN:
            it = snaps.get(sym)
            if not it:
                _log_skip("hedge_assets", sym, "quote_layer miss")
                continue
            d = dict(it); d["name"] = sym; d["cls"] = cls
            out.append(d)
        if len(out) < 4:
            _log_skip("hedge_assets", "plan", "legs<%d(FMP+Alpaca 双弱)" % len(out))
        return out
    return _wrap("hedge_assets", go)


def fetch_sectors():
    """爬虫#12:板块 tape(SPDR 11 + SMH)——quote_layer(FMP 主/Alpaca backup)。"""
    def go():
        plan = [("XLK", "XLK科技"), ("XLC", "XLC通信"), ("XLY", "XLY可选消费"),
                ("XLP", "XLP必选消费"), ("XLE", "XLE能源"), ("XLF", "XLF金融"),
                ("XLV", "XLV医疗"), ("XLI", "XLI工业"), ("XLB", "XLB材料"),
                ("XLRE", "XLRE地产"), ("XLU", "XLU公用"), ("SMH", "SMH半导体")]
        snaps = quote_layer_snapshot([p[0] for p in plan])
        out = []
        for sym, name in plan:
            it = snaps.get(sym)
            if it:
                d = dict(it); d["name"] = name
                out.append(d)
            else:
                _log_skip("sectors", sym, "quote_layer miss")
        return out
    return _wrap("sectors", go)


def fetch_fear_greed():
    """爬虫#9:CNN Fear & Greed(公开 dataviz 端点,零 key)——
    贪婪极值 + 指数冲高回落 = 拉高出货语境的情绪腿;端点若变响亮入 skip。"""
    def go():
        try:
            data = json.loads(_get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                                   {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                                    "Accept": "application/json",
                                    "Referer": "https://www.cnn.com/markets/fear-and-greed"}))   # v3.25:418 反爬对策,失败仍响亮入 skip
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


def fetch_earnings_calendar():
    """爬虫#10:Nasdaq 财报日历——上一交易日+今起5日。
    热日(昨+今)不设 15/80 cap——DOCS(~$4B,+68% AH)等中盘暴动否则被掐(patch 判例);
    未来日维持 15;源级 wrap 1200(≥800 门禁)以免热日全量再被吞。
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
                pri = d.get("primaryData") or {}
                sec = d.get("secondaryData") or {}
                p = _parse_money(pri.get("lastSalePrice"))
                x = _parse_money(sec.get("lastSalePrice"))
                # v3.25.4(8-20 BULL 反向读数案,戌抓获 v3.25.3 宣言未落地):
                # 盘后涨跌优先直取端点自算 secondaryData.percentageChange——不再跨
                # primary/secondary 两字段自己拼公式(深夜字段语义疑翻转,自拼即反向);
                # 端点缺该字段才回落自算兜底。双时戳+原始两价全落盘=语义定案材料。
                ahp = None
                pc = str(sec.get("percentageChange") or "").strip()
                if pc and pc not in ("--", "N/A"):
                    try:
                        ahp = round(float(pc.replace("%", "").replace("+", "")), 2)
                        if "-" in pc and ahp > 0:
                            ahp = -ahp
                    except ValueError:
                        ahp = None
                comp = round((x / p - 1) * 100, 2) if (x and p) else None
                conflict = (ahp is not None and comp is not None
                            and ((ahp > 0) != (comp > 0) or abs(ahp - comp) > 3))
                if conflict:
                    # 双算冲突绊线(8-20 BULL 案机械化):端点自算与本地自算方向相反或
                    # 差>3pp = 字段语义不可信,读数不采信不发布,两值+双时戳全录响亮。
                    _log_skip("afterhours", sym,
                              "盘后读数双算冲突不采信 endpoint=%+.2f%% computed=%+.2f%% (close_asof=%s ah_asof=%s)"
                              % (ahp, comp, pri.get("lastTradeTimestamp"), sec.get("lastTradeTimestamp")))
                    ahp = None
                if ahp is None and comp is not None and not conflict:
                    ahp = comp   # 兜底自算(端点缺字段且无冲突证据时)
                if p:
                    got = {"symbol": sym, "close": p, "ah_last": x, "ah_chg_pct": ahp,
                           "ah_conflict": bool(conflict),
                           "ah_pct_src": ("endpoint" if pc and pc not in ("--", "N/A") else "computed"),
                           "close_asof": pri.get("lastTradeTimestamp"),
                           "asof": sec.get("lastTradeTimestamp")}
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


# 十二爬虫全员(#11 liquidity_gate 按需;#12 sectors)· tape=quote_layer(FMP 主/Alpaca backup)
def _industry_cache_path():
    return os.path.join(os.path.dirname(_fmp_route_file()), ".industry_map.json")


def industry_lookup(syms):
    """行业标签查询(数据自聚热簇的分组键,替代手写主题表——2026-08-21 Lyra:
    禁写死范围,热点由数据自己聚)。FMP profile 端点族自探定版;每票终身缓存
    (行业极少变),仅新面孔发请求。失败的票标 industry=None,不阻塞。"""
    try:
        cache = json.load(open(_industry_cache_path(), encoding="utf-8"))
    except Exception:
        cache = {}
    if not _fmp_key():
        return {s: cache.get(s) for s in syms}
    route = _fmp_route_load()
    dirty = False
    for sym in syms:
        # v3.26.1:缓存项必须带 is_etf(ETF 不入池的硬判据);旧缓存缺该键或 None(旧版把 ETF
        # 空行业行当失败存 None)的票重查一次
        if isinstance(cache.get(sym), dict) and cache[sym].get("is_etf") is not None:
            continue
        cands = [_fmp_base() + "/profile/" + sym,
                 _FMP_STABLE_BASE + "/profile?symbol=" + sym]
        fam = route.get("profile")
        # 定版键=完整前缀 URL,精确前缀命中优先(戌 8-24 抓:旧裁剪裁到 …/stable
        # 两候选都匹配,二跑仍先打路径形 404;现按 fam 整串 startswith 精确分排)
        hit = [c for c in cands if fam and c.startswith(fam)]
        ordered = hit + [c for c in cands if c not in hit]
        got = None
        for u in ordered[:2]:
            try:
                raw = json.loads(_get(u + ("&" if "?" in u else "?") + "apikey=" + _fmp_key()))
                row = raw[0] if isinstance(raw, list) and raw else (raw if isinstance(raw, dict) else None)
                # ETF 的 profile 行业/板块常为空——按 isEtf/isFund 键在场也算有回包(legacy 与 stable
                # profile 均带 isEtf/isFund 字段);两键都不在 = 类型未证(None,候选池按未证不入)
                if row and (row.get("industry") or row.get("sector") or "isEtf" in row or "isFund" in row):
                    ie = (bool(row.get("isEtf")) or bool(row.get("isFund"))) \
                        if ("isEtf" in row or "isFund" in row) else None
                    got = {"industry": row.get("industry"), "sector": row.get("sector"), "is_etf": ie}
                    if route.get("profile") != u.split(sym)[0]:
                        route["profile"] = u.split(sym)[0]
                        _fmp_route_save()
                    break
            except Exception:
                continue
        cache[sym] = got
        dirty = True
    if dirty:
        try:
            json.dump(cache, open(_industry_cache_path(), "w", encoding="utf-8"), ensure_ascii=False)
        except Exception:
            pass
    return {s: cache.get(s) for s in syms}


def fetch_most_active():
    """爬虫#13(2026-08-21,crypto 板块三日连涨零覆盖案):最活跃榜=热资金直测。
    movers 榜抓单日暴动(top20 常被 +30% 小票占满),COIN/MARA/HOOD 型每天 +5-8%
    的稳步资金流进不了它——但成交最活跃榜必有它们。端点族自探定版(V6 判例),
    price≥3,cap 30。"""
    def go():
        if not _fmp_key():
            raise RuntimeError("FMP_API_KEY 未配置(most_active 依赖付费档)")
        # 端点候选按 FMP 官方文档实证(2026-08-21 守恒查证):legacy=/api/v3/actives
        # (官方 README 在册;/stock_market/actives 为守恒误推,降为第三候选防站点变体),
        # stable=/most-actives(官方 stable 文档 Top Traded Stocks API)。首个出数定版。
        urls = [_fmp_base() + "/actives", _FMP_STABLE_BASE + "/most-actives",
                _fmp_base() + "/stock_market/actives"]
        route = _fmp_route_load()
        rk = "movers:actives"
        fam = route.get(rk)
        ordered = ([fam] if fam in urls else []) + [u for u in urls if u != fam]
        errs, rows = [], None
        for u in ordered:
            try:
                raw = json.loads(_get(u + ("&" if "?" in u else "?") + "apikey=" + _fmp_key()))
                if isinstance(raw, list) and raw:
                    rows = raw
                    if route.get(rk) != u:
                        route[rk] = u
                        _fmp_route_save()
                    break
            except Exception as e:
                errs.append("%s -> %s" % (u.split("?")[0], str(e)[:90]))
        if rows is None:
            raise RuntimeError("most_active 两族全败:" + " | ".join(errs))
        out = []
        for r in rows:
            try:
                sym = (r.get("symbol") or r.get("ticker") or "").upper()
                px = float(r.get("price") or 0)
                chg = r.get("changesPercentage") or r.get("changePercentage") or r.get("changes")
                chg = float(str(chg).replace("%", "").replace("+", "")) if chg not in (None, "") else None
                if sym and px >= 3:
                    out.append({"symbol": sym, "price": px, "chg_pct": chg})
            except Exception:
                continue
        # _wrap 契约=返回扁平列表(2026-08-21 端到端抓获:dict 形状在 _wrap 切片处崩)
        return out[:30]
    return _wrap("most_active", go)


def fetch_market_movers():
    """爬虫#12(Lyra 拍板 2026-08-20,MRNA+143%/比特币板块/TEM 全盲案):全市场异动扫描。
    FMP gainers/losers 榜(非仅财报票)——|chg|≥10% 或榜单前列的个股进 raw,
    晚报复盘 watch 并入。端点族不猜:legacy 与 stable 候选逐个实弹,首个出数
    按 movers:方向 定版落盘 .fmp_route 跨班续用(V6 判例);全败=本班响亮停用。
    过滤:price≥3(防仙股噪音),每侧 cap 20。"""
    def go():
        if not _fmp_key():
            raise RuntimeError("FMP_API_KEY 未配置(movers 扫描依赖付费档)")
        cands = {
            "gainers": [_fmp_base() + "/stock_market/gainers",
                        _FMP_STABLE_BASE + "/biggest-gainers"],
            "losers": [_fmp_base() + "/stock_market/losers",
                       _FMP_STABLE_BASE + "/biggest-losers"],
        }
        route = _fmp_route_load()
        out = []
        for side, urls in cands.items():
            rk = "movers:%s" % side
            fam = route.get(rk)
            ordered = ([fam] if fam in urls else []) + [u for u in urls if u != fam]
            errs, rows = [], None
            for u in ordered:
                try:
                    data = json.loads(_fmp_get(u))
                    if isinstance(data, list) and data:
                        rows = data
                        if route.get(rk) != u:
                            route[rk] = u
                            _fmp_route_save()
                            print("[fetchers] fmp 路由定版 %s" % rk)
                        break
                    errs.append("空回包")
                except urllib.error.HTTPError as e:
                    errs.append(_http_err_text(e))
                except Exception as e:
                    errs.append(str(e)[:120])
            if rows is None:
                _log_skip("market_movers", side, "全候选失败: " + " | ".join(errs))
                continue
            kept = 0
            for r in rows:
                try:
                    sym = str(r.get("symbol") or "").upper()
                    px = float(r.get("price") or 0)
                    chg = r.get("changesPercentage")
                    chg = float(str(chg).strip("%()")) if chg is not None else None
                    if not re.fullmatch(r"[A-Z]{1,5}", sym) or px < 3 or chg is None:
                        continue
                    out.append({"symbol": sym, "side": side, "price": px,
                                "chg_pct": round(chg, 2), "name": str(r.get("name") or "")[:40]})
                    kept += 1
                    if kept >= 50:   # v3.26:20→50/侧(引擎渲染仍 cap 24,候选池地板筛)
                        break
                except Exception:
                    continue
        return out
    return _wrap("market_movers", go)


ALL = [fetch_treasury_yields, fetch_fred, fetch_indices, fetch_edgar_recent,
       fetch_fda_press, fetch_commodities, fetch_polymarket, fetch_hedge_assets,
       fetch_fear_greed, fetch_earnings_calendar, fetch_sectors, fetch_market_movers, fetch_most_active]


def run_all():
    SKIPS.clear()
    _QUOTE_MEMO.clear()
    print("[fetchers] " + data_plane_banner())
    res = [f() for f in ALL]
    if _fmp_key():
        print("[fetchers] FMP 当日用量 %d/%s(记账不设闸)" % (fmp_calls_today(), os.getenv("FMP_DAILY_BUDGET", "250")))
    return res
