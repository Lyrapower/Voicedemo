#!/usr/bin/env bash
# ============================================================================
# Scout Agent · v3.6 · 一键安装(守恒亲手交付;覆盖 v3.5)
#   v3.6(资金迁徙体制,Lyra 抛砖+守恒延伸):
#   ①#8 加 rotation 资产:FXI/KWEB/EWZ/EWJ/EEM/BABA(cls 标区分 hedge/rotation)
#   ②引擎新读数:rotation_leaders(海外领涨前三)+ rotation_divergence
#     (美股收跌而海外收涨=迁徙迹象,数字出引擎解读归 DS)
#   ③手册加"资金迁徙(海外)"regime:FXI/KWEB/EWZ/EWJ/EEM/BABA 单腿 call,
#     YINN 仅 T+0 决不隔夜(3x 日内重置损耗);ADR/中国 ETF=交易"明天的亚洲",
#     跳空风险进 abandon;两道护栏=挤兑日禁海外(EM beta 高跌更狠)、无分化读数禁海外
#   ④polymarket 事件词扩:china/hong kong/taiwan/brazil/japan/yuan/pboc/boj/emerging
#   v3.5(全线下跌体制,Lyra 提出+守恒延伸):
#   ①确定性跨资产引擎 cross_asset_summary:6 风险资产收跌面 + VIX 日变动 +
#     TLT/UUP 读数 + tape_flags;≥5/6 收跌且 VIX≥+8% → liquidation_watch 触发
#   ②对冲分级手册进 prompt:轮动日=商品 call;全线下跌日=商品 call 禁用,
#     切指数单腿 PUT / VIXY call / UUP,TLT 仅 flight-to-quality 被证实才用,
#     "减仓也是对冲"是合法结论;恐慌日买保险必须写 IV 高位代价与 vol crush 风险
#   ③#8 对冲池 +TLT +UUP;schema 加 hedge.regime;横幅挤兑红 chip;
#     两班简报页都带"跨资产引擎读数"卡(引擎数字独立于 DS 判断展示,可互相对质)
#   v3.4(Lyra 三补充 2026-08-05):
#   ①对冲铁律:晨会 schema 加 hedge 段(永不空白)——机构拉高出货/黑天鹅出尽情形
#     必须给 GLD/SLV/OXY/USO 对冲腿评估;"没信号什么都不写"被禁止;
#     横幅加出货风险 chip,对冲腿走 HEDGE 卡
#   ②九爬虫成军:+#8 hedge_assets(GLD/SLV/OXY/USO 日线)+#9 fear_greed(CNN);
#     indices/对冲资产统一日线帮手,确定性输出 close_loc 与 tape_flag
#     (冲高回落=拉高出货典型日线形——数字出引擎,解读归 DS);
#     晚报 9pm 加"风险雷达"节,黑天鹅/出货命中必须点名,未中明写"今日未见"
#   ③polymarket 加事件桶:经济/市场/地缘事件类(fed/recession/crash/tariff/war…)
#     全收 bucket=event,非事件类只留头部热度
#   v3.3(Lyra 三点整改 2026-08-05):
#   ①晨会单 DS 输出改严格 JSON schema(可审性:GLM 5.2 review/编译吃结构化数据,
#     console io_contract 直存 JSON;解析失败响亮降级不糊墙)
#   ②渲染层:briefs/日期-morning.html 卡片式简报(DESIGN_SPEC 同源 token)——
#     分节标题/横幅/个股 S2 式卡片(大 ticker/CALL·PUT 丸/入场·止损·作废·T+0 平仓/
#     展开解析=证据出处);空态卡"今日池内无事件驱动候选";evening 走 md 分节渲染,
#     两班都不再糊成一坨
#   ③交易风格偏置(硬约束):默认形态=T+0 单腿 CALL 当日了结,PUT 仅证据明确看空
#     才提且写明依据,禁多腿组合,禁编报价
#   DeepSeek(幻方量化)回归决策官:给方向/标的/行权价/策略/放弃条件的分析作业,
#   Lyra 拍板执行。
#   v3.2(Lyra 三拍板):①宇宙=SP500 & Nasdaq 池,不再是 SPY/QQQ 两 ETF——
#     晨会单改为"大盘方向+从池中提名具体标的",候选必须锚定隔夜采集证据,
#     禁凭训练记忆点名;新增指数采集源(^spx/^ndq/^vix,stooq 同端点零 key)
#   ②晨班 6:45→6:00 PST(=9:00 ET,盘前一小时,"开盘在即"措辞自此成立)
#   ③evening_brief.py 删除(晚班由 scout_agent --mode evening 独家,不再双线)
#   v3.1 修复保留:合成数据闸门/yesterday_raw 字典序洞/polymarket skip 源名/
#     plist SCOUT_OUT/edgar 死 URL 清理
#   双班:morning 6:00 交易任务单(workstation 联动)/ evening 9pm 复盘+弹药
#   bash scout_agent_install_v3_6.sh [目标目录]   默认 ./grid-scout
#   首跑三步见 README.md
# ============================================================================
set -euo pipefail
ROOT="${1:-./grid-scout}"
mkdir -p "$ROOT"
cd "$ROOT"

cat > 'README.md' <<'PKG_EOF_000'
# Scout Agent v3(DeepSeek 决策官版,守恒亲手交付)

DeepSeek(幻方量化基因)= 交易台参谋。给方向判断/关键行权价/具体策略/
放弃条件的**分析作业**——给 Lyra 看的参谋作业,Lyra 自己拍板执行。
建议 ≠ 自动下单信号:DS 出分析,人做决定,主频在 Lyra。
宇宙 = S&P 500 & Nasdaq 成分池(Lyra 拍板 2026-08-05,不再是 SPY/QQQ 两 ETF);
候选必须锚定隔夜采集证据,禁凭训练记忆点名。

## 双班
- morning 6:00am PST(=9:00 ET 盘前):结构化交易任务单(拉 workstation GEX+隔夜 raw
  → DS 决策官五段:大盘方向+置信度 / 池内候选(锚定证据) / 关键价位 /
  具体策略含行权价到期最大亏损 / 放弃条件)
- evening 9pm:复盘+明日弹药(要闻催化 / 赔率变化 / 明日日历 / 明日关注方向)

## 三步上岗
1. `DEEPSEEK_API_KEY` 填两个 plist(platform.deepseek.com);
   `curl -s https://api.deepseek.com/models -H "Authorization: Bearer $KEY"` 验模型名
2. 首跑:`python3 scout_agent.py --mode morning --skip-fetch`
   → 看 briefs/日期-morning.md 是否含"阻力/支撑/具体行权价/放弃条件"
3. 两个 plist 替换 __SCOUT_DIR__ 与 FILL_ME 后 launchctl load(晚 21:00 / 晨 6:00)

## 数据联动
morning 先拉 workstation :8620 的 net_gex/gamma_flip/IVP/VRP 喂给 DS;
:8620 不可达则 DS 基于隔夜数据判断,不阻塞。

## 落档与渲染(v3.3)
DS 作业 → console deepseek_lane 任务(晨会为 JSON 存档,GLM 5.2 review/编译直接吃)
+ briefs/ 三件落盘:.md 原文、.html 卡片式简报(分节标题+个股 S2 式卡片+空态卡)、
.json(晨会,结构化可审)。console 不可达则仅本地落盘(响亮记录)。
JSON 解析失败 → 响亮降级为文本分节渲染,永不糊墙。

## 交易风格偏置(v3.3 硬约束)
默认形态 = T+0 单腿 CALL 当日了结(t0_exit 必填);PUT 仅证据明确看空;禁多腿;禁编报价。

## 对冲铁律(v3.4/v3.5)
九爬虫:国债收益率/FRED/指数(含 tape_flag)/EDGAR/FDA/商品/Polymarket(含事件桶)/
对冲资产 GLD·SLV·OXY·USO·TLT·UUP + 迁徙资产 FXI·KWEB·EWZ·EWJ·EEM·BABA/Fear&Greed。
晨会 hedge 段与晚报风险雷达永不空白;对冲分体制:
- 轮动/拉高出货 → GLD/SLV/OXY/USO 单腿 call
- 资金迁徙(美股跌而海外分化走强)→ FXI/KWEB/EWZ/EWJ/EEM/BABA 单腿 call,
  YINN 仅 T+0;护栏:挤兑日与无分化读数时禁海外腿
- 全线下跌(引擎 liquidation_watch:≥5/6 风险资产收跌+VIX≥+8%)→ 商品 call 禁用,
  海外也不是避风港;切指数单腿 PUT / VIXY call / UUP;TLT 仅当其当日为正;
  "减仓/空仓也是对冲"必须写成结论;恐慌日保险要写 IV 代价与 vol crush 风险。
PKG_EOF_000

cat > 'com.grid.evening-brief.plist' <<'PKG_EOF_001'
<?xml version="1.0" encoding="UTF-8"?>
<!-- 模板:是否注册常驻由 Lyra 拍板后自行执行(铁则:不默认引入常驻项)
     cp 到 ~/Library/LaunchAgents/ 后:launchctl load ~/Library/LaunchAgents/com.grid.evening-brief.plist -->
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.grid.evening-brief</string>
  <key>ProgramArguments</key>
  <array><string>/usr/bin/python3</string><string>__SCOUT_DIR__/scout_agent.py</string>
         <string>--mode</string><string>evening</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>21</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>__SCOUT_DIR__/scout.log</string>
  <key>StandardErrorPath</key><string>__SCOUT_DIR__/scout.err</string>
  <key>EnvironmentVariables</key><dict>
    <key>SCOUT_OUT</key><string>__SCOUT_DIR__</string>
    <key>CONSOLE_URL</key><string>http://localhost:8610</string>
    <key>CONSOLE_KEY</key><string>FILL_ME</string>
    <key>DEEPSEEK_API_KEY</key><string>FILL_ME</string>
    <key>FRED_API_KEY</key><string></string>
  </dict>
</dict></plist>
PKG_EOF_001

cat > 'com.grid.morning-brief.plist' <<'PKG_EOF_002'
<?xml version="1.0" encoding="UTF-8"?>
<!-- 晨报 6:00am PST(=9:00 ET,盘前一小时;Lyra 拍板 2026-08-05);注册: cp 到 ~/Library/LaunchAgents 后 launchctl load -->
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.grid.morning-brief</string>
  <key>ProgramArguments</key>
  <array><string>/usr/bin/python3</string><string>__SCOUT_DIR__/scout_agent.py</string>
         <string>--mode</string><string>morning</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>6</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>__SCOUT_DIR__/scout_morning.log</string>
  <key>StandardErrorPath</key><string>__SCOUT_DIR__/scout_morning.err</string>
  <key>EnvironmentVariables</key><dict>
    <key>SCOUT_OUT</key><string>__SCOUT_DIR__</string>
    <key>CONSOLE_URL</key><string>http://localhost:8610</string>
    <key>CONSOLE_KEY</key><string>FILL_ME</string>
    <key>DEEPSEEK_API_KEY</key><string>FILL_ME</string>
    <key>FRED_API_KEY</key><string></string>
  </dict>
</dict></plist>
PKG_EOF_002


cat > 'fetchers.py' <<'PKG_EOF_004'
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
PKG_EOF_004

cat > 'scout_agent.py' <<'PKG_EOF_005'
#!/usr/bin/env python3
"""scout_agent.py —— Scout Agent v3(DeepSeek 决策官版,守恒手写)
DeepSeek(幻方量化基因)= 交易台参谋,给方向/行权价/策略/放弃条件的分析作业。
建议 ≠ 自动信号:DS 出的是给 Lyra 看的决策官作业,Lyra 自己拍板买不买。
双班:evening 9pm 复盘+明日弹药 / morning 6:00 PST 结构化交易任务单。
数据联动:morning 拉 workstation(:8620)GEX/特征 + 隔夜 raw,喂给 DS 做判断。
宇宙 = SP500 & Nasdaq 成分池;候选锚定隔夜采集证据,禁凭记忆点名。
"""
from __future__ import annotations
import argparse, datetime, html, json, os, re, sys, urllib.request

import fetchers

DS_BASE = os.getenv("DEEPSEEK_BASE", "https://api.deepseek.com")
DS_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DS_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
CONSOLE = os.getenv("CONSOLE_URL", "http://localhost:8610")
CONSOLE_KEY = os.getenv("CONSOLE_KEY", "").strip()
OWS = os.getenv("OWS_URL", "http://localhost:8620")
OUT = os.getenv("SCOUT_OUT", os.path.expanduser("~/grid-scout"))


def _http(url, body=None, headers=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ---- workstation 数据联动 ----
def fetch_workstation_state():
    try:
        dates = _http(OWS + "/api/dates", timeout=5)
        if not dates:
            return None
        d = _http(OWS + "/api/day/" + dates[-1], timeout=5)
        ws = {"date": dates[-1], "underlying": d["snap"]["underlying"],
              "spot": d["snap"]["spot"], "net_gex": d["gex"]["net_gex_musd_per_1pct"],
              "gamma_flip": d["gex"]["gamma_flip"], "ivp": d["features"]["ivp"],
              "vrp": d["features"]["vrp20"], "source": d["snap"].get("source")}
        if str(ws["source"] or "").startswith("synthetic"):
            print("[scout] workstation 仅合成演示数据(%s)——不作数,不喂 DS" % ws["source"])
            return None
        return ws
    except Exception as e:
        print("[scout] workstation(:8620) 不可达:", e)
        return None


def yesterday_raw(today):
    """按日期前缀取上一交易日最新落盘。
    旧实现 f < today+'.json' 有洞:'-HHMM.json' 字典序 < '.json',
    今日自己的重跑后缀文件会被当成"昨日对比"。"""
    try:
        rawdir = os.path.join(OUT, "raw")
        cand = [f for f in os.listdir(rawdir) if f.endswith(".json") and f[:10] < today]
        if cand:
            last_day = max(f[:10] for f in cand)
            pick = max((f for f in cand if f[:10] == last_day),
                       key=lambda f: os.path.getmtime(os.path.join(rawdir, f)))
            return json.load(open(os.path.join(rawdir, pick), encoding="utf-8"))
    except Exception:
        pass
    return None


# ---- DS 决策官 prompt(v3.2 池化:大盘方向+池内提名) ----
def build_trading_prompt(raw, ws, yday, cross=None):
    return f"""你是交易台的首席决策官。开盘在即,基于隔夜数据给出清晰的分析作业
(这是给交易员参考的分析,交易员自己拍板执行,不是自动下单)。
观察宇宙 = S&P 500 与 Nasdaq 成分池(不是 SPY/QQQ 两只 ETF)。

隔夜采集:{json.dumps(raw, ensure_ascii=False)[:6000]}
工作站读数(GEX/特征):{json.dumps(ws, ensure_ascii=False) if ws else "工作站无可用实弹数据(不可达或仅合成数据),基于隔夜数据判断"}
昨日采集(对比用):{json.dumps(yday, ensure_ascii=False)[:2000] if yday else "无"}
跨资产引擎读数(确定性,判断必须引用):{json.dumps(cross, ensure_ascii=False) if cross else "无"}

交易风格偏置(硬约束):交易员主做 T+0 单腿 CALL,当日了结。
- 策略默认形态 = 单腿 CALL,到期选 0DTE 或最近可用到期,必须给 t0_exit(当日平仓纪律)
- PUT 仅当看空证据明确时才提,并在 evidence 写清依据;禁止多腿组合;禁止编造权利金/报价
候选铁律:每个候选必须锚定隔夜采集中的具体条目(EDGAR/FDA/赔率/指数与宏观读数),
逐条给出处;无证据则 candidates 留空并填 no_candidate_reason;禁止凭训练记忆点名。
对冲铁律(hedge 段永不空白——"没信号什么都不写"被禁止):
- 用跨资产引擎读数 + fear_greed 评估风险,先定 regime,写进 distribution_risk + basis
- 风险 中/高 → 必须按下表给 1-2 条对冲腿;风险 低 → note 写明依据(不许留空)
对冲分级手册(按 regime 选工具,用错工具比不对冲更糟):
- regime=轮动/拉高出货(股冲高回落或收跌,但 GLD/油有买盘):
  GLD/SLV/OXY/USO 单腿 call,T+0 纪律照旧
- regime=全线下跌(engine liquidation_watch=true:风险资产≥5/6 收跌+VIX≥+8%):
  黄金原油也在跌——商品 call 不是对冲,禁用。工具切换为:
  ①指数单腿 PUT(SPY/QQQ;对冲工具不受候选宇宙池化令限制)
  ②VIXY 单腿 call——流动性挤兑日唯一确定被买的是波动率
  ③UUP call(现金涌向美元);TLT 仅当 tlt_chg_pct>0(flight-to-quality 被证实)才可用,
    利率冲击型下跌里 TLT 同跌,禁用
  ④"减仓/空仓也是对冲"是合法结论——但必须写成结论,不许留白
  ⑤IV 代价必须写:恐慌日买 put/VIX call 是在 IV 高位买保险,strategy 里写明
    隔夜 vol crush 风险与 t0_exit
- regime=资金迁徙(海外)(SP500 收跌但 rotation_divergence 非空——资金不会消失只会转移):
  海外腿可用:FXI/KWEB(中国)、EWZ(巴西)、EWJ(日本)、EEM(新兴)、BABA 单腿 call,
  evidence 必须引用 rotation_leaders 的具体涨跌数字;
  YINN(3x 中国)仅限 T+0 决不隔夜——杠杆 ETF 日内重置损耗,拿隔夜是给做市商送钱;
  美股时段的中国 ETF/ADR 交易的是"明天的亚洲",隔夜跳空风险必须写进 abandon
- 护栏一:全线下跌日(liquidation_watch=true)禁点海外腿——global margin call 无避风港,
  新兴市场 beta 更高、流动性更差,挤兑日跌更狠
- 护栏二:rotation_divergence 为空时同禁海外腿——没有分化读数就没有迁徙证据
- evidence 锚定引擎读数与 hedge_assets/fear_greed 数字,禁编报价

只输出一个 JSON 对象——不要 markdown、不要代码围栏、不要 JSON 之外的任何文字。schema:
{{"macro": {{"sp500_bias": "看涨|看跌|中性震荡", "nasdaq_bias": "看涨|看跌|中性震荡",
  "confidence": "高|中|低", "logic": "引用 indices/收益率/VIX/赔率读数的推理",
  "key_levels": "大盘关键位(无实弹 GEX 时如实写依据)"}},
 "candidates": [{{"ticker": "", "direction": "call|put",
   "evidence": [{{"source": "edgar|fda|polymarket|indices|macro", "item": "条目摘要", "why": "为何构成驱动"}}],
   "key_levels": "该标的阻力/支撑及依据",
   "strategy": {{"type": "单腿 call", "strike_logic": "行权价选择逻辑(不编报价)",
     "expiry": "0DTE|本周五|最近到期", "entry_condition": "入场触发条件",
     "stop": "止损条件", "abandon": "作废条件", "t0_exit": "当日平仓纪律"}}}}],
 "no_candidate_reason": "candidates 为空时的证据核查结论,否则空串",
 "hedge": {{"distribution_risk": "高|中|低", "regime": "轮动|资金迁徙(海外)|全线下跌|无明显风险",
   "basis": "引用跨资产引擎/fear_greed/hedge_assets 读数的依据",
   "legs": [{{"ticker": "GLD|SLV|OXY|USO|TLT|UUP|VIXY|SPY|QQQ|FXI|KWEB|EWZ|EWJ|EEM|BABA|YINN", "direction": "call|put",
     "evidence": [{{"source": "hedge_assets|fear_greed|indices|macro", "item": "读数", "why": "为何对冲"}}],
     "strategy": {{"type": "单腿 call", "strike_logic": "", "expiry": "0DTE|本周五|最近到期",
       "entry_condition": "", "stop": "", "abandon": "", "t0_exit": ""}}}}],
   "note": "风险低暂不对冲时写明依据;永不空白"}},
 "data_gaps": [{{"item": "", "status": "", "handling": ""}}],
 "conclusion": "一句话结论"}}
禁止"具体视情况而定""谨慎操作"等无效废话。全部值用中文。"""


def build_evening_prompt(raw, yday, cross=None):
    return f"""你是交易台参谋。写今日收盘复盘 + 明日弹药,给交易员看:
1. 今日要闻与并购/FDA/事件催化(带出处)
2. 隔夜→今日的赔率变化(Polymarket)
3. 明日日历(FDA/到期/财报/事件)
4. 明日值得盯的方向与关键位(分析,非指令)
5. 风险雷达(黑天鹅/机构拉高出货/全线下跌排查,永不留空):逐项核对——
   跨资产引擎读数(liquidation_watch、tape_flags、vix_chg_pct)、fear_greed 极值、
   hedge_assets 异动、polymarket bucket=event 赔率突变;
   命中拉高出货 → 点名并给商品对冲方向(GLD/SLV/OXY/USO);
   命中资金迁徙(rotation_divergence 非空)→ 点名领涨海外腿(引用 rotation_leaders 数字),
   给 FXI/KWEB/EWZ/EWJ/EEM/BABA 方向,YINN 注明仅 T+0;
   命中全线下跌(liquidation_watch=true)→ 明写"商品 call 不是对冲、海外也不是避风港",
   给指数 PUT/VIXY/UUP 方向与"减仓也是对冲";未命中则明写"今日未见"
跨资产引擎读数:{json.dumps(cross, ensure_ascii=False) if cross else "无"}
今日采集:{json.dumps(raw, ensure_ascii=False)[:6000]}
昨日对比:{json.dumps(yday, ensure_ascii=False)[:1500] if yday else "无"}
用 markdown,严格以 ## 分节(要闻催化/赔率变化/明日日历/明日方向/风险雷达),
每节内用短段落或列表,不要糊成整段。用中文,给数字给出处,不写废话。"""


def ds_call(prompt):
    if not DS_KEY:
        raise SystemExit(
            "[scout] DEEPSEEK_API_KEY 未配置。\n"
            "  1) platform.deepseek.com 注册取 key,填 .env 或 plist\n"
            "  2) curl -s %s/models -H 'Authorization: Bearer $DEEPSEEK_API_KEY' 验模型名\n"
            "  3) 实况名与默认 %s 不符则设 DEEPSEEK_MODEL" % (DS_BASE, DS_MODEL))
    r = _http(DS_BASE + "/chat/completions",
              {"model": DS_MODEL, "max_tokens": 2000,
               "messages": [{"role": "user", "content": prompt}]},
              {"Authorization": "Bearer " + DS_KEY})
    return r["choices"][0]["message"]["content"]


def cross_asset_summary(payload):
    """确定性跨资产读数(数字出引擎,解读归 DS)。
    全线下跌体制判据:6 只风险资产(SP500/NASDAQ/GLD/SLV/OXY/USO)≥5 收跌
    且 VIX 单日 ≥ +8%——此时黄金原油同跌,商品 call 不构成对冲。"""
    m = {}
    for src in (payload.get("results") or payload.get("sources") or []):
        if src.get("source") in ("indices", "hedge_assets"):
            for it in src.get("items", []):
                if isinstance(it, dict) and it.get("name"):
                    m[it["name"]] = it
    risk = ["SP500", "NASDAQ", "GLD", "SLV", "OXY", "USO"]
    downs = [n for n in risk if n in m and (m[n].get("chg_pct") or 0) < 0]
    vix = (m.get("VIX") or {}).get("chg_pct")
    rot = {n: v for n, v in m.items() if v.get("cls") == "rotation"}
    spx_chg = (m.get("SP500") or {}).get("chg_pct") or 0
    leaders = sorted(((n, v.get("chg_pct")) for n, v in rot.items()
                      if v.get("chg_pct") is not None), key=lambda x: -x[1])[:3]
    out = {"risk_assets_down": downs, "down_count": len(downs), "of": len(risk),
           "vix_chg_pct": vix,
           "tlt_chg_pct": (m.get("TLT") or {}).get("chg_pct"),
           "uup_chg_pct": (m.get("UUP") or {}).get("chg_pct"),
           "tape_flags": {n: m[n]["tape_flag"] for n in m if m[n].get("tape_flag")},
           "rotation_leaders": [{"name": n, "chg_pct": c} for n, c in leaders],
           # 分化=资金迁徙迹象:美股收跌而海外腿收涨(数字出引擎,解读归 DS)
           "rotation_divergence": ([n for n, v in rot.items() if (v.get("chg_pct") or 0) > 0]
                                   if spx_chg < 0 else []),
           "liquidation_watch": len(downs) >= 5 and (vix or 0) >= 8.0}
    return out


def _extract_json(text):
    """从 DS 回复抽 JSON(容忍围栏/前后杂讯);抽不出返回 None,上游响亮降级。"""
    t = text or ""
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        try:
            return json.loads(t[i:j + 1])
        except Exception:
            return None
    return None


# ---- 渲染层(DESIGN_SPEC 同源 token;卡片式简报,不再糊墙) ----
BRIEF_CSS = """
:root{--bg:#07090e;--panel:rgba(17,22,34,.78);--line:rgba(126,148,190,.13);
--ink:#e3eaf6;--dim:#8a97ad;--faint:#5a6478;--gold:#e2b95f;--grn:#57d19e;
--red:#ef5f79;--f1:12px;--f2:14px;--f3:16px;--f6:28px;
--sans:-apple-system,"PingFang SC","Hiragino Sans GB",sans-serif;
--mono:ui-monospace,SFMono-Regular,Menlo,monospace}
*{box-sizing:border-box}
body{margin:0;padding:0 0 60px;background:var(--bg);color:var(--ink);font:var(--f2)/1.65 var(--sans)}
.num{font-family:var(--mono);font-variant-numeric:tabular-nums}
header{position:sticky;top:0;display:flex;gap:12px;align-items:center;height:48px;padding:0 14px;
background:rgba(7,9,14,.92);border-bottom:1px solid var(--line);z-index:5}
header h1{font:700 var(--f3) var(--mono);letter-spacing:.18em;margin:0}
header .sub{color:var(--faint);font-size:var(--f1)}
.banner{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:12px;padding:9px 14px;
border:1px solid var(--line);border-radius:10px;background:rgba(11,15,24,.72);font-size:var(--f1)}
.banner b{font-size:var(--f2)}
section{margin:0 12px 14px}
h2{font-size:var(--f1);color:var(--dim);letter-spacing:.12em;margin:18px 2px 8px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:12px}
.badge{display:inline-block;border:1px solid var(--grn);color:var(--grn);border-radius:999px;
padding:2px 12px;font:var(--f1) var(--mono)}
.tick{display:flex;gap:12px;align-items:center;margin:8px 0 2px}
.tick .sym{font:700 var(--f6) var(--mono);letter-spacing:.04em}
.pill{border:1.5px solid var(--grn);color:var(--grn);border-radius:999px;padding:2px 14px;font:600 var(--f2) var(--mono)}
.pill.put{border-color:var(--red);color:var(--red)}
.kv{display:flex;justify-content:space-between;gap:14px;padding:4px 0;font-size:var(--f2);
border-bottom:1px dashed rgba(126,148,190,.08)}
.kv:last-child{border:0}
.kv b{color:var(--dim);font-weight:500;white-space:nowrap}
.kv span{text-align:right}
details{margin-top:10px}
summary{cursor:pointer;color:#7ea6e8;font-size:var(--f2)}
.ev{border-left:2px solid var(--line);padding:6px 0 6px 12px;margin:8px 0}
.ev .src{color:var(--gold);font:var(--f1) var(--mono)}
.ev .why{color:var(--dim);font-size:var(--f1)}
.empty{border:1px dashed var(--line);border-radius:12px;padding:20px;color:var(--dim);text-align:center;line-height:1.8}
table{width:100%;border-collapse:collapse;font-size:var(--f1)}
th{color:var(--dim);text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);font-weight:500}
td{padding:5px 8px;border-bottom:1px solid rgba(126,148,190,.06);vertical-align:top}
p{margin:7px 0}
footer{margin:24px 12px 0;color:var(--faint);font-size:10px;font-family:var(--mono)}
"""


def _esc(x):
    return html.escape(str(x if x is not None else ""))


def _cand_card(c, tag, badge="SCOUT"):
    d = (c.get("direction") or "call").lower()
    st = c.get("strategy") or {}
    evs = "".join(
        '<div class="ev"><div class="src">%s</div><div>%s</div><div class="why">%s</div></div>'
        % (_esc(e.get("source", "")), _esc(e.get("item", "")), _esc(e.get("why", "")))
        for e in (c.get("evidence") or [])) or '<div class="ev">(无证据条目——按铁律本卡不应存在)</div>'
    rows = [("形态", st.get("type")), ("行权价逻辑", st.get("strike_logic")),
            ("到期", st.get("expiry")), ("入场条件", st.get("entry_condition")),
            ("止损", st.get("stop")), ("作废条件", st.get("abandon")),
            ("T+0 平仓", st.get("t0_exit")), ("关键位", c.get("key_levels"))]
    kvs = "".join('<div class="kv"><b>%s</b><span>%s</span></div>' % (l, _esc(v)) for l, v in rows if v)
    return ('<div class="card"><span class="badge">%s %s</span>'
            '<div class="tick"><span class="sym">%s</span><span class="pill%s">%s</span></div>%s'
            '<details><summary>展开解析(证据出处)</summary>%s</details></div>'
            % (badge, _esc(tag), _esc((c.get("ticker") or "?").upper()),
               " put" if d == "put" else "", d.upper(), kvs, evs))


def _render_structured(date, data):
    m = data.get("macro") or {}
    cands = data.get("candidates") or []
    gaps = data.get("data_gaps") or []
    hd = data.get("hedge") or {}
    risk = hd.get("distribution_risk") or "—"
    rc = {"高": "var(--red)", "中": "var(--gold)", "低": "var(--grn)"}.get(risk, "var(--dim)")
    out = ['<div class="banner"><b>晨会交易任务单</b><span class="num">%s</span>'
           '<span>SP500 <b>%s</b></span><span>NASDAQ <b>%s</b></span><span>置信 <b>%s</b></span>'
           '<span>出货风险 <b style="color:%s">%s</b></span></div>'
           % (_esc(date), _esc(m.get("sp500_bias", "—")), _esc(m.get("nasdaq_bias", "—")),
              _esc(m.get("confidence", "—")), rc, _esc(risk))]
    out.append('<section><h2>一 · 大盘方向</h2><div class="card">'
               '<div class="kv"><b>逻辑</b><span>%s</span></div>'
               '<div class="kv"><b>关键位</b><span>%s</span></div></div></section>'
               % (_esc(m.get("logic", "")), _esc(m.get("key_levels", ""))))
    if cands:
        out.append('<section><h2>二 · 池内候选(默认形态:T+0 单腿 CALL)</h2>%s</section>'
                   % "".join(_cand_card(c, date) for c in cands))
    else:
        out.append('<section><h2>二 · 池内候选</h2><div class="empty">今日池内无事件驱动候选'
                   '<br><span style="font-size:var(--f1)">%s</span></div></section>'
                   % _esc(data.get("no_candidate_reason", "")))
    hcard = ('<div class="card"><div class="kv"><b>风险评估</b>'
             '<span style="color:%s">%s</span></div>'
             '<div class="kv"><b>依据</b><span>%s</span></div>%s</div>'
             % (rc, _esc(risk), _esc(hd.get("basis", "")),
                ('<div class="kv"><b>说明</b><span>%s</span></div>' % _esc(hd.get("note"))) if hd.get("note") else ""))
    out.append('<section><h2>三 · 对冲(拉高出货/黑天鹅雷达)</h2>%s%s</section>'
               % (hcard, "".join(_cand_card(l, date, "HEDGE") for l in (hd.get("legs") or []))))
    if gaps:
        out.append('<section><h2>四 · 数据缺失与矛盾标注</h2><div class="card"><table>'
                   '<tr><th>项目</th><th>状态</th><th>处理</th></tr>%s</table></div></section>'
                   % "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
                             % (_esc(g.get("item")), _esc(g.get("status")), _esc(g.get("handling")))
                             for g in gaps))
    if data.get("conclusion"):
        out.append('<section><h2>五 · 结论</h2><div class="card">%s</div></section>'
                   % _esc(data.get("conclusion")))
    return "".join(out)


def _md_fallback(text):
    """markdown → 分节 HTML(晚报常规路径;晨会 JSON 解析失败的降级路径)。不再糊墙。"""
    out, buf = [], []
    def flush():
        if buf:
            out.append("<p>%s</p>" % "<br>".join(buf)); buf.clear()
    for ln in (text or "").splitlines():
        t = ln.strip()
        if not t or t == "---":
            flush(); continue
        if t.startswith("#"):
            flush(); out.append("<h2>%s</h2>" % _esc(t.lstrip("#").strip()))
        else:
            e = _esc(t)
            e = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", e)
            buf.append(e)
    flush()
    return '<section><div class="card">%s</div></section>' % "".join(out)


def _engine_card(cross):
    if not cross:
        return ""
    liq = cross.get("liquidation_watch")
    downs = ",".join(cross.get("risk_assets_down") or []) or "无"
    flags = ";".join("%s=%s" % kv for kv in (cross.get("tape_flags") or {}).items()) or "无"
    leaders = " · ".join("%s %+.2f%%" % (x.get("name"), x.get("chg_pct"))
                          for x in (cross.get("rotation_leaders") or []) if x.get("chg_pct") is not None) or "无读数"
    div = ",".join(cross.get("rotation_divergence") or []) or "无"
    rows = [("风险资产收跌", "%s / %s(%s)" % (cross.get("down_count"), cross.get("of"), downs)),
            ("VIX 日变动", "%s%%" % cross.get("vix_chg_pct")),
            ("TLT / UUP", "%s%% / %s%%" % (cross.get("tlt_chg_pct"), cross.get("uup_chg_pct"))),
            ("资金迁徙(海外领涨)", leaders),
            ("迁徙分化(美股跌而其涨)", div),
            ("tape flags", flags),
            ("全线下跌判据", "触发——商品 call 不是对冲,海外也不是避风港" if liq else "未触发")]
    kvs = "".join('<div class="kv"><b>%s</b><span>%s</span></div>' % (l, _esc(v)) for l, v in rows)
    return '<section><h2>〇 · 跨资产引擎读数(确定性)</h2><div class="card">%s</div></section>' % kvs


def render_brief_html(date, mode, data, raw_text, cross=None):
    warn = ""
    if (cross or {}).get("liquidation_watch"):
        warn = ('<div class="banner" style="border-color:var(--red)">'
                '<b style="color:var(--red)">全线下跌 WATCH</b>'
                '<span>风险资产 %s/%s 收跌 · VIX %s%% · 商品 call 不是对冲</span></div>'
                % (_esc(cross.get("down_count")), _esc(cross.get("of")), _esc(cross.get("vix_chg_pct"))))
    body = warn + _engine_card(cross) + (_render_structured(date, data) if data else _md_fallback(raw_text))
    return ('<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"/>'
            '<meta name="viewport" content="width=device-width,initial-scale=1"/>'
            '<title>SCOUT · %s · %s</title><style>%s</style></head><body>'
            '<header><h1>SCOUT</h1><span class="sub">%s · %s · 参谋作业,Lyra 拍板</span></header>'
            '%s<footer>build scout v3.3 · DS 决策官 JSON 结构化 · 无证据不点名 · 合成 GEX 不作数 · '
            '渲染:_render_structured/_cand_card/_md_fallback</footer></body></html>'
            % (mode.upper(), _esc(date), BRIEF_CSS, mode, _esc(date), body))


def render_console(title, body, date, mode, data=None, cross=None):
    """DS 作业进 console 落档(work_log 入魂器);console 不可达则本地落盘。"""
    payload_doc = ("[DS 决策官作业·JSON(GLM review/编译直接吃)] "
                   + json.dumps(data, ensure_ascii=False)[:8000]) if data else \
                  ("[DS 决策官作业,存档] " + body[:8000])
    try:
        if not CONSOLE_KEY:
            raise RuntimeError("CONSOLE_KEY 未配置")
        t = _http(CONSOLE + "/api/tasks",
                  {"workspace": "trade", "title": title, "owner_node": "deepseek_lane",
                   "risk_level": "read", "io_contract": payload_doc},
                  {"X-Console-Key": CONSOLE_KEY})
        print("[scout] console 任务 DS#%s(work_log 入魂器)" % t.get("task_id"))
    except Exception as e:
        print("[scout] console 不可达(%s)→ 本地落盘" % e)
    bdir = os.path.join(OUT, "briefs")
    os.makedirs(bdir, exist_ok=True)
    bp = os.path.join(bdir, "%s-%s.md" % (date, mode))
    with open(bp, "w", encoding="utf-8") as f:
        f.write("# %s\n\n%s\n" % (title, body))
    hp = os.path.join(bdir, "%s-%s.html" % (date, mode))
    with open(hp, "w", encoding="utf-8") as f:
        f.write(render_brief_html(date, mode, data, body, cross))
    if data is not None:
        with open(os.path.join(bdir, "%s-%s.json" % (date, mode)), "w", encoding="utf-8") as f:
            json.dump({"_engine": cross, "ds": data}, f, ensure_ascii=False, indent=1)
    print("[scout] 落盘:", bp, "+", hp, "(+json)" if data is not None else "")


def main():
    ap = argparse.ArgumentParser(description="Scout Agent v3(DS 决策官)")
    ap.add_argument("--mode", choices=["evening", "morning"], default="evening")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-fetch", action="store_true")
    a = ap.parse_args()
    today = datetime.date.today().isoformat()
    os.makedirs(os.path.join(OUT, "raw"), exist_ok=True)
    raw_path = os.path.join(OUT, "raw", today + ".json")

    if a.skip_fetch and os.path.exists(raw_path):
        payload = json.load(open(raw_path, encoding="utf-8"))
        print("[scout] --skip-fetch 复用", raw_path)
    else:
        results = fetchers.run_all()
        payload = {"results": results, "skips": fetchers.SKIPS}
        if os.path.exists(raw_path):
            raw_path = raw_path.replace(".json", "-" + datetime.datetime.now().strftime("%H%M") + ".json")
        json.dump(payload, open(raw_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        ok = sum(1 for r in payload["results"] if r["ok"])
        print("[scout] %s 源成功 %d/%d → %s" % (today, ok, len(payload["results"]), raw_path))
        for b in payload["results"]:
            if not b["ok"]:
                print("   ✗", b["source"], b.get("error", ""))

    if a.dry_run:
        print("[scout] --dry-run 止步于采集"); return

    yday = yesterday_raw(today)
    cross = cross_asset_summary(payload)
    if cross.get("liquidation_watch"):
        print("[scout] 引擎:全线下跌判据触发", cross)
    if a.mode == "morning":
        ws = fetch_workstation_state()
        body = ds_call(build_trading_prompt(payload, ws, yday, cross))
        data = _extract_json(body)
        if data is None:
            print("[scout] DS 未按 JSON schema 输出——晨会单降级为文本分节渲染(响亮记录)")
        render_console("Scout 晨会交易任务单 · " + today, body, today, "morning", data, cross)
    else:
        body = ds_call(build_evening_prompt(payload, yday, cross))
        render_console("Scout 晚报复盘 · " + today, body, today, "evening", None, cross)


if __name__ == "__main__":
    main()
PKG_EOF_005
chmod +x scout_agent.py 2>/dev/null || true
echo ""; echo "✓ Scout Agent v3: $(pwd) — 首跑 python3 scout_agent.py --mode morning --skip-fetch"
