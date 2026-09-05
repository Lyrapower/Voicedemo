#!/usr/bin/env python3
"""scout_agent.py —— Scout Agent v3(DeepSeek 决策官版,守恒手写)
DeepSeek(幻方量化基因)= 交易台参谋,给方向/行权价/策略/放弃条件的分析作业。
建议 ≠ 自动信号:DS 出的是给 Lyra 看的决策官作业,Lyra 自己拍板买不买。
双班:evening 9pm 复盘+明日弹药 / morning 6:45 PST(盘初)结构化交易任务单。
数据联动:morning 拉 workstation(:8620)GEX/特征 + 隔夜 raw,喂给 DS 做判断。
宇宙(三层):SP500&Nasdaq 主池 / 事件驱动个股不限成分(过流动性闸)/ 海外 ADR 巨头;
候选锚定隔夜采集证据,禁凭记忆点名。复盘回路:晚班确定性复盘→次晨战绩入 prompt。
v3.15 = 两窗合流:amc_tonight/cap 族谱四层(邻窗)∪ 晚班movers/真实ET/EDGAR锚定/README真源(守恒)。
v3.16 = 晚班修复:§5 AMC 已出叙事 / §6 run-up 仅未来日 / et_now_hm 钟点 / review.watch 收编雷达名单。
v3.16.2 = tape_check 引擎盖章 + 晨会 RSI 禁自估 + amc_tonight 带 Alpaca 读数 + yday 截断 4000。
v3.16§⑦ = quote_layer 缝(Alpaca)/feed 档/盘后格式;stooq 退役→指数商品 ETF 代理。
"""
from __future__ import annotations
import argparse, datetime, html, json, os, re, sys, urllib.error, urllib.request

import fetchers

DS_BASE = os.getenv("DEEPSEEK_BASE", "https://api.deepseek.com")
DS_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DS_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
CONSOLE = os.getenv("CONSOLE_URL", "http://localhost:8610")
CONSOLE_KEY = os.getenv("CONSOLE_KEY", "").strip()
OWS = os.getenv("OWS_URL", "http://localhost:8620")
GW = os.getenv("GATEWAY_URL", "http://127.0.0.1:8501").rstrip("/")
OUT = os.getenv("SCOUT_OUT", os.path.dirname(os.path.abspath(__file__)))


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
def build_trading_prompt(raw, ws, yday, cross=None, prev=None):
    return f"""你是交易台的首席决策官。现在是 ET {fetchers.et_now_hm()}
(常规调度 = 9:45 ET 开盘后15分钟;交易员在美西 PST。若当前非常规时刻——手动重跑——读数按实际时刻解读),
基于隔夜数据 + 盘初 tape 给出清晰的分析作业
(这是给交易员参考的分析,交易员自己拍板执行,不是自动下单)。
观察宇宙(2026-08-06 扩定,三层):
A. S&P 500 与 Nasdaq 成分池(主池,不是 SPY/QQQ 两只 ETF)
B. 事件驱动个股不限成分——8-K 并购/FDA 等隔夜证据命中的美股可点名,但必须过流动性闸:
   大中盘、期权活跃;小盘或期权价差宽的宁可不点,T+0 会死在价差上
C. 海外 ADR 巨头(BABA/PDD/JD/TSM/NVO 级别)——迁徙或自身事件驱动时可点,
   时差跳空风险写进 abandon
每个候选必须填 liquidity 字段:一句话说明流动性为何扛得住 T+0。
读数口径提醒:indices/hedge_assets 的当日行是盘初部分K线(开盘~15分钟,非收盘),
chg_pct 是盘初对昨收,tape_flag/close_loc 按盘初形态解读,不当全日形态用;
昨日完整形态看晚报与昨日采集。

隔夜采集:{json.dumps(raw, ensure_ascii=False)[:6000]}
工作站读数(GEX/特征):{json.dumps(ws, ensure_ascii=False) if ws else "工作站无可用实弹数据(不可达或仅合成数据),基于隔夜数据判断"}
昨日采集(对比用):{json.dumps(yday, ensure_ascii=False)[:2000] if yday else "无"}
跨资产引擎读数(确定性,判断必须引用):{json.dumps(cross, ensure_ascii=False) if cross else "无"}
昨日战绩(确定性复盘,必须引用):{json.dumps(prev, ensure_ascii=False) if prev else "无(首日或昨日无产出)"}

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
财报两步手册(earnings_calendar 采集必须核对;候选撞财报必须在 earnings_note 声明):
- 第一步·财报/重大消息当日:禁开盘第一根追入——高 IV + 双向扫损 = 多空双杀;
  合法入场 = IV crush 落地后、盘初区间(约首30分钟)方向突破确认再进,0DTE 此时才合法
- 第二步·财报前 run-up(公布前 2-8 个交易日):可做预期抢跑 call,买"预期+IV 双升"
  (vega 顺风);铁律 = 财报公布前必须离场,赚 run-up 不赌事件;
  今日 AMC 出财报的标的,T+0 收盘前清仓(本来就是纪律,此处双重锁死)
- 第三步·财报次日(昨夜 AMC 已出结果,今晨 gap):IV 已 crush——单腿 call 的黄金窗口之一;
  gap-and-go = 盘初 30 分钟站稳开盘价上方再追;首 30 分钟回补 gap 过半 = fade,放弃做多;
  方向已被结果定调,禁逆结果抄底/摸顶
- 候选 5 个交易日内有财报 → earnings_note 写明日期/BMO 或 AMC/采用哪条手册;无则写"无"
今晚 AMC 规则(引擎 amc_tonight 名单必须核对):
- 名单内标的财报今晚才出——只能按手册第二步(run-up)评估,earnings_note 必须写
  "今日 AMC,收盘前清仓";禁持仓过财报,禁赌结果
- 点不点名是 DS 的判断;但名单前三(按市值)未点名时,须在 rejected 或正文给一句理由
主菜优先级(堵"抓小众漏大鱼",TEAM 案例后立):
- 引擎 earnings_movers 榜首 |chg_pct|≥8% 的标的必须显式处理——进 candidates 评估,
  或进 rejected 写明理由;禁止无痕跳过
- 候选所属板块应与引擎 sector_leaders 对齐;背离必须在排名理由里解释
战绩与 RSI 铁律:
- 昨日方向错的腿,今日同逻辑再点必须写明"昨日同逻辑失误 + 今日为何不同";
  滚动命中率 <50% → 整体压低置信度表述
- RSI14 是时机过滤器不是方向信号:凡采集读数中有 rsi14 者(指数/对冲/movers/amc 名单),
  >70 禁追高须写回踩确认、<30 禁追空;读数里没有的标的**禁止自估 RSI**——
  引擎将在你输出后逐腿实测盖章(tape_check),违规会被红标对质;对冲腿同规
数字纪律(机构级;违者视为编造):
- 一切绝对数字(价位/市值/百分比)必须能在本 prompt 的采集读数中逐一找到,
  并标明来源;找不到 → 只许相对表述(昨收/盘初高点/前日低点),禁止精确小数价位
- 大盘 key_levels 同规:引擎只有日线读数、没有盘中报价——禁止给精确指数点位,
  一律相对位表述
- 概率用词("上行概率高""65%")必须带来源(polymarket 具体市场/引擎读数);无源禁用
- 市值/期权活跃度若无采集来源,liquidity 里必须写明"估计,无实测来源"

只输出一个 JSON 对象——不要 markdown、不要代码围栏、不要 JSON 之外的任何文字。schema:
{{"macro": {{"sp500_bias": "看涨|看跌|中性震荡", "nasdaq_bias": "看涨|看跌|中性震荡",
  "confidence": "高|中|低", "logic": "引用 indices/收益率/VIX/赔率读数的推理",
  "key_levels": "大盘关键位——相对表述(昨收/盘初高低点),无盘中报价禁精确点位"}},
 "candidates": [{{"ticker": "", "direction": "call|put",
   "evidence": [{{"source": "edgar|fda|polymarket|indices|macro", "item": "条目摘要", "why": "为何构成驱动"}}],
   "key_levels": "该标的阻力/支撑及依据",
   "liquidity": "一句话:市值/期权活跃度为何扛得住 T+0",
   "strategy": {{"type": "单腿 call", "strike_logic": "行权价选择逻辑(不编报价)",
     "expiry": "0DTE|本周五|最近到期", "entry_condition": "入场触发条件",
     "stop": "止损条件", "abandon": "作废条件",
     "earnings_note": "5个交易日内财报:日期/BMO或AMC/采用哪条手册;无则写无",
     "t0_exit": "当日平仓纪律"}}}}],
 "no_candidate_reason": "candidates 为空时的证据核查结论,否则空串",
 "rejected": [{{"ticker": "", "reason": "一句话淘汰理由(候选漏斗可审;考虑过但没入选的,最多3条)"}}],
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


def build_evening_prompt(raw, yday, cross=None, review=None):
    # v3.16: ET 真实钟点 + §5 已出叙事 + §6 run-up 仅未来日 + watch 复盘
    return f"""你是交易台参谋。现在是 ET {fetchers.et_now_hm()}(收盘后;今日 AMC 财报已披露)。
写今日收盘复盘 + 明日弹药,给交易员看:
1. 今日要闻与并购/FDA/事件催化(带出处)
2. 隔夜→今日的赔率变化(Polymarket)
3. 明日日历(FDA/到期/财报/事件)
4. 明日值得盯的方向与关键位(分析,非指令)
5. 风险雷达(黑天鹅/机构拉高出货/全线下跌排查,永不留空):逐项核对——
   跨资产引擎读数(liquidation_watch、tape_flags、vix_chg_pct)、fear_greed 极值、
   hedge_assets 异动、polymarket bucket=event 赔率突变;
   财报异动榜(earnings_movers/earnings_calendar)有 |chg|≥8% 者必须点名讲清楚;
   今晚 AMC(amc_tonight)= 财报"已出结果"者名单,晚班一律按已出叙事——
   禁止出现"财报前/若超预期/待公布"类措辞;逐个点名并给明晨手册第三步路径
   (gap-and-go / 回补过半 fade 判据);
   盘后:有 amc_ah_tape 则必须写「盘后 xx(feed档, HH:MM ET)」并引 source/feed_label
   (例:盘后 140.45(盘后·IEX 口径, 16:30 ET));无则明写"盘后读数缺失",禁编数字
   (点名依据=名单本身,不做"谁出了结果"的侦测);
   命中拉高出货 → 点名并给商品对冲方向(GLD/SLV/OXY/USO);
   命中资金迁徙(rotation_divergence 非空)→ 点名领涨海外腿(引用 rotation_leaders 数字),
   给 FXI/KWEB/EWZ/EWJ/EEM/BABA 方向,YINN 注明仅 T+0;
   命中全线下跌(liquidation_watch=true)→ 明写"商品 call 不是对冲、海外也不是避风港",
   给指数 PUT/VIXY/UUP 方向与"减仓也是对冲";未命中则明写"今日未见"
6. 晨会复盘与明日调优(复盘读数必须逐腿引用,方向命中口径=收盘对昨收):
   逐腿讲对错与原因假设;给明日晨会具体调优——哪些逻辑降权、入场条件怎么改、
   RSI 时机过滤:必须引用引擎 rsi14_tape 实测数字(指数/对冲腿);
   有数则点名 SP500/NASDAQ 等 rsi14;某腿 rsi14 为 null 才可写「该腿无实测」,
   禁止整节写「当前无数据,假设中性」;
   明日及以后(date>今日)的财报名单从 earnings_calendar 点名,标注 run-up 机会;
   今日已出结果者不属 run-up,禁入此节(其复盘走 watch 段与风险雷达)
   watch 段(雷达名单收盘读数)逐个讲清,尤其 |chg|≥8% 者——这是"看见了但没入选"
   的复盘;此后 TEAM 类标的必须在复盘留痕,空缺即故障
数字纪律同晨会:绝对数字必须有采集来源并标明,无源用相对表述;概率词必须带来源。
复盘读数(确定性):{json.dumps(review, ensure_ascii=False) if review else "今日无晨会腿可复盘"}
跨资产引擎读数:{json.dumps(cross, ensure_ascii=False) if cross else "无"}
今日采集:{json.dumps(raw, ensure_ascii=False)[:6000]}
昨日对比:{json.dumps(yday, ensure_ascii=False)[:4000] if yday else "无"}
用 markdown,严格以 ## 分节(要闻催化/赔率变化/明日日历/明日方向/风险雷达/晨会复盘与明日调优),
每节内用短段落或列表,不要糊成整段。用中文,给数字给出处,不写废话。"""


def ds_call(prompt):
    if not DS_KEY:
        raise SystemExit(
            "[scout] DEEPSEEK_API_KEY 未配置。\n"
            "  1) platform.deepseek.com 注册取 key,填 .env 或 plist\n"
            "  2) curl -s %s/models -H 'Authorization: Bearer $DEEPSEEK_API_KEY' 验模型名\n"
            "  3) 实况名与默认 %s 不符则设 DEEPSEEK_MODEL" % (DS_BASE, DS_MODEL))
    # Ollama deepseek-v4-pro:cloud 默认会开 think → content 空;本机约定关 think
    # 偶发仍空:重试一次(同一 think=false),禁止把 reasoning 当正文。
    last_err = None
    for attempt in range(2):
        body = {
            "model": DS_MODEL,
            "max_tokens": int(os.getenv("DEEPSEEK_MAX_TOKENS", "8000")),
            "messages": [{"role": "user", "content": prompt}],
        }
        if "11434" in DS_BASE or "ollama" in DS_BASE.lower():
            body["think"] = False
        try:
            r = _http(DS_BASE + "/chat/completions", body,
                      {"Authorization": "Bearer " + DS_KEY}, timeout=300)
        except Exception as e:
            last_err = e
            continue
        msg = ((r.get("choices") or [{}])[0].get("message") or {})
        text = (msg.get("content") or "").strip()
        if text:
            return text
        last_err = "empty content (reasoning_len=%d)" % len(
            str(msg.get("reasoning") or msg.get("reasoning_content") or "")
        )
        print("[scout] DS 空正文 attempt=%d %s" % (attempt + 1, last_err))
    raise SystemExit("[scout] DS 空正文 model=%s(须 think=false) last=%s"
                     % (DS_MODEL, last_err))


def cross_asset_summary(payload):
    """确定性跨资产读数(数字出引擎,解读归 DS)。
    全线下跌体制判据:6 只风险资产(SP500/NASDAQ/GLD/SLV/OXY/USO)≥5 收跌
    且 VIX 单日 ≥ +8%——此时黄金原油同跌,商品 call 不构成对冲。
    v3.8 修复:run_all 落盘键是 results,此前只读 sources——引擎在现网从未吃到数据,
    liquidation_watch/迁徙读数一直空转(自测喂了手搓 schema,没走 main 形状,守恒之过)。"""
    m = {}
    for src in payload.get("results", payload.get("sources", [])):
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
           "sector_leaders": [], "sector_laggards": [],
           # 分化=资金迁徙迹象:美股收跌而海外腿收涨(数字出引擎,解读归 DS)
           "rotation_divergence": ([n for n, v in rot.items() if (v.get("chg_pct") or 0) > 0]
                                   if spx_chg < 0 else []),
           "liquidation_watch": len(downs) >= 5 and (vix or 0) >= 8.0}
    sec = []
    for src in payload.get("results", payload.get("sources", [])):
        if src.get("source") == "sectors":
            sec = [x for x in src.get("items", []) if isinstance(x, dict) and x.get("chg_pct") is not None]
    sec.sort(key=lambda x: -x["chg_pct"])
    out["sector_leaders"] = [{"name": x["name"], "chg_pct": x["chg_pct"]} for x in sec[:3]]
    out["sector_laggards"] = [{"name": x["name"], "chg_pct": x["chg_pct"]} for x in sec[-3:]] if len(sec) >= 3 else []
    # 时机过滤器实测截面——晚报 RSI 节必须引用此表,禁写「无数据假设中性」
    rsi_tape = []
    for n in ("SP500", "NASDAQ", "VIX", "GLD", "SLV", "OXY", "TLT"):
        it = m.get(n) or {}
        if it.get("rsi14") is not None or it.get("chg_pct") is not None:
            rsi_tape.append({
                "name": n, "rsi14": it.get("rsi14"), "chg_pct": it.get("chg_pct"),
                "close_loc": it.get("close_loc"),
            })
    out["rsi14_tape"] = rsi_tape
    return out


def _review_files():
    b = os.path.join(OUT, "briefs")
    if not os.path.isdir(b):
        return []
    return sorted(f for f in os.listdir(b) if f.endswith("-review.json"))


def _review_tape(sym, skip_src="review"):
    """复盘取数:Alpaca/quote_layer(stooq 已退役)。"""
    if hasattr(fetchers, "quote_layer"):
        return (fetchers.quote_layer.snapshot([sym]) or {}).get(sym)
    if hasattr(fetchers, "alpaca_snapshots"):
        return (fetchers.alpaca_snapshots([sym]) or {}).get(sym)
    return None


def build_review(date, engine_extra=None):
    """确定性复盘(晚班 21:00 跑,拿全日K线):读当日晨会 json,逐腿取收盘涨跌/
    close_loc/RSI14,判方向命中。v3.16:watch=amc_tonight前8+movers前3收盘存证,不计命中率。
    engine_extra=晚班当场引擎(覆盖晨会 _engine 里的名单,保证今日 AMC 进 watch)。"""
    mp = os.path.join(OUT, "briefs", "%s-morning.json" % date)
    if not os.path.exists(mp):
        return None
    doc = json.load(open(mp, encoding="utf-8"))
    ds = doc.get("ds") or doc
    legs = list(ds.get("candidates") or []) + list((ds.get("hedge") or {}).get("legs") or [])
    out = []
    for l in legs:
        t = (l.get("ticker") or "").upper()
        if not re.fullmatch(r"[A-Z]{1,5}", t or ""):
            print("[scout] 复盘跳过非常规代码:", t)
            continue
        d = _review_tape(t, "review")
        if not d:
            continue
        direction = (l.get("direction") or "call").lower()
        chg = d.get("chg_pct") or 0
        out.append({"ticker": t, "direction": direction, "chg_pct": d.get("chg_pct"),
                    "close_loc": d.get("close_loc"), "rsi14": d.get("rsi14"),
                    "hit": chg > 0 if direction == "call" else chg < 0})
    eng = dict(doc.get("_engine") or {})
    if engine_extra:
        eng.update(engine_extra)
    watch, seen = [], {x["ticker"] for x in out}
    amc_rows = list(eng.get("amc_tonight") or [])
    amc_syms = [_amc_row_sym(x) for x in amc_rows]
    for sym in amc_syms[:8] + \
               [m.get("symbol") for m in (eng.get("earnings_movers") or [])[:3]]:
        if not sym or sym in seen or not re.fullmatch(r"[A-Z]{1,5}", sym):
            continue
        seen.add(sym)
        d = _review_tape(sym, "review_watch")
        if d:
            watch.append({"ticker": sym, "chg_pct": d.get("chg_pct"),
                          "close_loc": d.get("close_loc"), "tag": "watch"})
    # TEAM 类留痕:在 amc_tonight 内但落在前8之外时仍进 watch(验收硬项)
    for sym in ("TEAM",):
        if sym in amc_syms and sym not in seen:
            seen.add(sym)
            d = _review_tape(sym, "review_watch")
            if d:
                watch.append({"ticker": sym, "chg_pct": d.get("chg_pct"),
                              "close_loc": d.get("close_loc"), "tag": "watch"})
    if not out and not watch:
        return None
    nh = sum(1 for x in out if x["hit"])
    rev = {"date": date, "legs": out, "watch": watch,
           "hit": "%d/%d" % (nh, len(out)) if out else "0/0",
           "hit_rate": round(nh / len(out), 2) if out else None,
           "basis": "收盘对昨收判定方向命中(仅 DS 腿);watch=雷达名单收盘存证,不计命中率"}
    os.makedirs(os.path.join(OUT, "briefs"), exist_ok=True)
    with open(os.path.join(OUT, "briefs", "%s-review.json" % date), "w", encoding="utf-8") as f:
        json.dump(rev, f, ensure_ascii=False, indent=1)
    return rev


def load_prev_review(today):
    files = [f for f in _review_files() if f[:10] < today]
    if not files:
        return None
    return json.load(open(os.path.join(OUT, "briefs", files[-1]), encoding="utf-8"))


def rolling_summary(upto_incl):
    files = [f for f in _review_files() if f[:10] <= upto_incl][-5:]
    tot = hit = 0
    for fn in files:
        r = json.load(open(os.path.join(OUT, "briefs", fn), encoding="utf-8"))
        for l in r.get("legs") or []:
            tot += 1
            hit += 1 if l.get("hit") else 0
    return {"days": len(files), "legs": tot,
            "hit_rate_pct": round(100 * hit / tot, 1) if tot else None} if files else None


def earnings_movers(payload, today):
    """确定性财报异动榜(堵 TEAM 案例:昨夜 AMC 暴涨 31% 晨会却推原油):
    昨日 AMC + 今日 BMO 财报名单逐个取盘初 tape,按 |chg| 排序前8——
    最大 catalyst 从此结构性可见,数字出引擎解读归 DS。"""
    yd = fetchers.prev_trading_day(datetime.date.fromisoformat(today)).isoformat()   # 跳周末:周一看上周五 AMC
    syms = []
    for src in payload.get("results", payload.get("sources", [])):
        if src.get("source") == "earnings_calendar":
            for it in src.get("items", []):
                sym = (it.get("symbol") or "").upper()
                if not re.fullmatch(r"[A-Z]{1,5}", sym):
                    continue
                d, when = it.get("date"), (it.get("when") or "")
                if d == yd and "after" in when:
                    syms.append((sym, "昨日AMC"))
                elif d == today and "pre" in when:
                    syms.append((sym, "今日BMO"))
    out = []
    # 中游 cap 20→30:上游热日解封后此处仍 20 = 盲区挪层(同族第三处,守恒补刀);
    # 中游上限 30;榜单仍只出前 8(Alpaca 批量)
    ordered = []
    seen = set()
    for sym, tag in syms[:30]:
        if sym in seen:
            continue
        seen.add(sym)
        ordered.append((sym, tag))
    snaps = {}
    if hasattr(fetchers, "quote_layer"):
        snaps = fetchers.quote_layer.snapshot([s for s, _ in ordered]) or {}
    elif hasattr(fetchers, "alpaca_snapshots"):
        snaps = fetchers.alpaca_snapshots([s for s, _ in ordered])
    for sym, tag in ordered:
        r = snaps.get(sym)
        if r and r.get("chg_pct") is not None:
            out.append({"symbol": sym, "when": tag, "chg_pct": r["chg_pct"],
                        "close_loc": r.get("close_loc"), "rsi14": r.get("rsi14")})
    out.sort(key=lambda x: -abs(x["chg_pct"]))
    return out[:8]


def _amc_row_sym(x):
    """amc_tonight 元素:str 或 {symbol,...} → SYM。"""
    if isinstance(x, dict):
        return (x.get("symbol") or "").upper()
    return (x or "").upper()


def amc_tonight(payload, today):
    """确定性名单:今日 AMC——晨会时财报未出,不进 movers 硬闸;晚班按已出点名。
    v3.16.2:返回带 chg/rsi/close_loc 的 dict 列表(本机 Alpaca 批量盖章,禁自估)。
    名单保日历市值序;取前40(TEAM 等中盘);批量取数有界(≠逐票 stooq×15)。"""
    out = []
    for src in payload.get("results", payload.get("sources", [])):
        if src.get("source") == "earnings_calendar":
            for it in src.get("items", []):
                sym = (it.get("symbol") or "").upper().replace(".", "-")
                if it.get("date") == today and "after" in (it.get("when") or "") \
                        and re.fullmatch(r"[A-Z]{1,5}", sym):
                    out.append(sym)
    # "已出结果者"的判定 = 名单本身(晚班时点今日 AMC 基本已全部披露)。
    # 禁止从数据里"侦测谁出了结果"——任何侦测都是编。
    out = out[:40]
    snaps = {}
    if out and hasattr(fetchers, "alpaca_snapshots"):
        snaps = fetchers.alpaca_snapshots(out) or {}
    out2 = []
    for sym in out:
        d = snaps.get(sym) or {}
        out2.append({
            "symbol": sym,
            "chg_pct": d.get("chg_pct"),
            "rsi14": d.get("rsi14"),
            "close_loc": d.get("close_loc"),
            "source": d.get("source") or ("alpaca" if d else None),
        })
    return out2


def _amc_sym_list(amc_syms, force=("TEAM",)):
    syms, seen = [], set()
    for s in list(force) + list(amc_syms or []):
        u = _amc_row_sym(s)
        if not u or u in seen or not re.fullmatch(r"[A-Z]{1,5}", u):
            continue
        seen.add(u)
        syms.append(u)
    return syms


def amc_session_tape(amc_syms, *, force=("TEAM",), limit=12):
    """今晚 AMC 名单的「常规时段」tape(Alpaca 日线)——供晚报逐票复盘。
    口径:RTH 收盘价,不是盘后财报反应价。晚报另有 amc_ah_tape。"""
    syms = _amc_sym_list(amc_syms, force=force)
    if not syms:
        return []
    snaps = {}
    if hasattr(fetchers, "alpaca_snapshots"):
        snaps = fetchers.alpaca_snapshots(syms)
    rows = []
    for sym in syms:
        r = snaps.get(sym) or {}
        if r.get("chg_pct") is None:
            continue
        rows.append({
            "symbol": sym,
            "when": "今日AMC",
            "session": "regular",
            "phase": "RTH_pre_print_or_into_close",
            "chg_pct": r.get("chg_pct"),
            "close_loc": r.get("close_loc"),
            "rsi14": r.get("rsi14"),
            "close": r.get("close"),
            "note": "常规时段(RTH)实测——晚报语境下财报多半已出;盘后反应见 amc_ah_tape",
        })
    force_set = {str(x).upper() for x in force}
    forced = [x for x in rows if x["symbol"] in force_set]
    rest = sorted(
        [x for x in rows if x["symbol"] not in force_set],
        key=lambda x: -abs(x.get("chg_pct") or 0),
    )
    return (forced + rest)[:limit]


def amc_ah_tape(amc_syms, *, force=("TEAM",), limit=12):
    """今日 AMC 盘后 tape——经 quote_layer.snapshot(v3.16§⑦)。
    有 ah_price 才入表;展示口径=「盘后 xx(feed档, HH:MM ET)」;无则 DS 写读数缺失。"""
    syms = _amc_sym_list(amc_syms, force=force)
    if not syms or not hasattr(fetchers, "quote_layer"):
        return []
    snaps = fetchers.quote_layer.snapshot(syms) or {}
    rows = []
    for sym in syms:
        r = snaps.get(sym) or {}
        if r.get("ah_price") is None:
            continue
        if abs(r.get("ah_vs_rth_pct") or 0) < 0.3 and abs(r.get("ah_vs_prev_pct") or 0) < 0.3:
            continue
        rows.append({
            "symbol": sym,
            "when": "今日AMC",
            "session": "after_hours",
            "phase": "AH_post_print",
            "mid": r.get("ah_price"),
            "bid": r.get("ah_bid"),
            "ask": r.get("ah_ask"),
            "rth_close": r.get("close"),
            "vs_rth_pct": r.get("ah_vs_rth_pct"),
            "vs_prev_pct": r.get("ah_vs_prev_pct"),
            "quote_ts": r.get("ah_ts") or r.get("latest_trade_ts") or r.get("latest_quote_ts"),
            "ah_et_hm": r.get("ah_et_hm"),
            "feed": r.get("feed"),
            "feed_label": r.get("feed_label") or (
                fetchers.feed_ah_label() if hasattr(fetchers, "feed_ah_label") else ""
            ),
            "ah_display": r.get("ah_display"),
            "source": r.get("source") or "alpaca",
            "latest_trade_ts": r.get("latest_trade_ts"),
            "note": "quote_layer 盘后实测;数字以 ah_ts/feed_label 为准",
        })
    force_set = {str(x).upper() for x in force}
    forced = [x for x in rows if x["symbol"] in force_set]
    rest = sorted(
        [x for x in rows if x["symbol"] not in force_set],
        key=lambda x: -abs(x.get("vs_rth_pct") or 0),
    )
    return (forced + rest)[:limit]


def apply_liquidity_gate(data):
    """确定性流动性闸(爬虫#11):候选+对冲腿逐个实测市值/日均量,盖 liquidity_check 章。
    v3.16.2:同构加 tape_check(RSI/chg/close_loc)——只盖章不删卡,拍板在 Lyra。
    本机 tape 供数=Alpaca/quote_layer(stooq 已退役);地板 env LIQ_MCAP_FLOOR_B,默认 $2.0B。"""
    legs = list(data.get("candidates") or []) + list((data.get("hedge") or {}).get("legs") or [])
    syms = sorted({(l.get("ticker") or "").upper() for l in legs
                   if re.fullmatch(r"[A-Z]{1,5}", (l.get("ticker") or "").upper())})
    if not syms:
        return data
    res = fetchers.fetch_ticker_liquidity(syms)
    m = {i["symbol"]: i for i in (res.get("items") or [])}
    floor = fetchers.LIQ_MCAP_FLOOR_B
    snaps = {}
    if hasattr(fetchers, "quote_layer"):
        snaps = fetchers.quote_layer.snapshot(syms) or {}
    elif hasattr(fetchers, "alpaca_snapshots"):
        snaps = fetchers.alpaca_snapshots(syms) or {}
    for l in legs:
        sym = (l.get("ticker") or "").upper()
        i = m.get(sym)
        if not i:
            l["liquidity_check"] = {"mcap_b": None, "floor_b": floor,
                                    "verdict": "无实测——DS 的 liquidity 按估计对待"}
        else:
            ok = i["mcap_b"] is not None and i["mcap_b"] >= floor
            l["liquidity_check"] = {"mcap_b": i["mcap_b"], "avg_vol": i.get("avg_vol"), "floor_b": floor,
                                    "verdict": "过闸" if ok else ("未过闸(<$%.1fB)——谨慎,拍板在 Lyra" % floor)}
        td = snaps.get(sym)
        if td:
            rsi, dirn = td.get("rsi14"), (l.get("direction") or "call").lower()
            v = ("违规:RSI%.0f 超买,追高需回踩确认" % rsi) if (rsi and rsi > 70 and dirn == "call") \
                else (("违规:RSI%.0f 超卖,禁追空" % rsi) if (rsi and rsi < 30 and dirn == "put") else "过")
            l["tape_check"] = {"rsi14": rsi, "chg_pct": td.get("chg_pct"),
                               "close_loc": td.get("close_loc"), "verdict": v,
                               "source": td.get("source") or "alpaca"}
        else:
            l["tape_check"] = {"rsi14": None, "verdict": "无实测"}
    return data


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
.kv.bad span{color:var(--red);font-weight:600}
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
    lc = c.get("liquidity_check") or {}
    lc_txt = (("$%.2fB · %s" % (lc["mcap_b"], lc.get("verdict", ""))) if lc.get("mcap_b") is not None
              else lc.get("verdict"))
    tc = c.get("tape_check") or {}
    tc_txt = (("RSI %s · 盘初 %+.2f%% · %s" % (
        tc.get("rsi14") if tc.get("rsi14") is not None else "—",
        tc.get("chg_pct") or 0, tc.get("verdict") or "")) if tc else None)
    rows = [("形态", st.get("type")), ("行权价逻辑", st.get("strike_logic")),
            ("到期", st.get("expiry")), ("入场条件", st.get("entry_condition")),
            ("止损", st.get("stop")), ("作废条件", st.get("abandon")),
            ("财报", st.get("earnings_note")), ("流动性(DS)", c.get("liquidity")),
            ("流动性实测(引擎)", lc_txt),
            ("RSI/tape 实测(引擎)", tc_txt),
            ("T+0 平仓", st.get("t0_exit")), ("关键位", c.get("key_levels"))]
    kvs = "".join(
        '<div class="kv%s"><b>%s</b><span>%s</span></div>' % (
            ' bad' if (l.startswith("RSI/tape") and "违规" in str(v)) else "",
            l, _esc(v))
        for l, v in rows if v)
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
    rej = data.get("rejected") or []
    if rej:
        out.append('<section><h2>二·附 · 已淘汰候选(漏斗可审)</h2><div class="card">%s</div></section>'
                   % "".join('<div class="kv"><b>%s</b><span>%s</span></div>'
                             % (_esc(r.get("ticker")), _esc(r.get("reason"))) for r in rej))
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
    movers = " · ".join("%s %+.1f%%(%s)" % (x["symbol"], x["chg_pct"], x["when"])
                         for x in (cross.get("earnings_movers") or [])[:4]) or None
    if movers:
        rows.append(("财报异动(昨AMC/今BMO)", movers))
    if cross.get("amc_tonight"):
        def _amc_chip(x):
            if isinstance(x, dict):
                sym = x.get("symbol") or "?"
                chg = x.get("chg_pct")
                return ("%s%+.1f%%" % (sym, chg)) if chg is not None else str(sym)
            return str(x)
        rows.append(("今晚财报(AMC watch)",
                     " · ".join(_amc_chip(x) for x in cross["amc_tonight"][:6])))
    amc_tape = cross.get("amc_session_tape") or []
    if amc_tape:
        rows.append((
            "AMC常规时段tape",
            " · ".join(
                "%s%+.1f%%(rsi%s)" % (
                    x.get("symbol"), x.get("chg_pct") or 0,
                    x.get("rsi14") if x.get("rsi14") is not None else "—",
                )
                for x in amc_tape[:6]
            ),
        ))
    ah_tape = cross.get("amc_ah_tape") or []
    if ah_tape:
        rows.append((
            "AMC盘后报价(已出结果)",
            " · ".join(
                (x.get("ah_display") or "%s 盘后 %.2f(%s, %s ET)%+.1f%%vsRTH" % (
                    x.get("symbol"), x.get("mid") or 0,
                    x.get("feed_label") or "?", x.get("ah_et_hm") or "??:??",
                    x.get("vs_rth_pct") or 0,
                ))
                for x in ah_tape[:6]
            ),
        ))
    sl = cross.get("sector_leaders") or []
    sg = cross.get("sector_laggards") or []
    if sl:
        rows.append(("板块热力", "领:%s · 尾:%s"
                     % (" ".join("%s %+.1f%%" % (x["name"], x["chg_pct"]) for x in sl),
                        " ".join("%s %+.1f%%" % (x["name"], x["chg_pct"]) for x in sg))))
    pr = cross.get("prev_review") or cross.get("today_review")
    if pr:
        rows.append(("战绩 %s" % (pr.get("date") or ""),
                     "%s 命中 · 滚动%s日 %s%%" % (pr.get("hit", "—"),
                     (pr.get("rolling") or {}).get("days", "—"),
                     (pr.get("rolling") or {}).get("hit_rate_pct", "—"))))
    kvs = "".join('<div class="kv"><b>%s</b><span>%s</span></div>' % (l, _esc(v)) for l, v in rows)
    return '<section><h2>〇 · 跨资产引擎读数(确定性)</h2><div class="card">%s</div></section>' % kvs


def render_brief_html(date, mode, data, raw_text, cross=None):
    warn = ""
    if (cross or {}).get("liquidation_watch"):
        warn = ('<div class="banner" style="border-color:var(--red)">'
                '<b style="color:var(--red)">全线下跌 WATCH</b>'
                '<span>风险资产 %s/%s 收跌 · VIX %s%% · 商品 call 不是对冲</span></div>'
                % (_esc(cross.get("down_count")), _esc(cross.get("of")), _esc(cross.get("vix_chg_pct"))))
    plane = ""
    if hasattr(fetchers, "data_plane_banner"):
        plane = ('<div class="banner"><b>数据层</b><span>%s</span></div>'
                 % _esc(fetchers.data_plane_banner()))
    body = (plane + warn + _engine_card(cross)
            + (_render_structured(date, data) if data else _md_fallback(raw_text)))
    return ('<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"/>'
            '<meta name="viewport" content="width=device-width,initial-scale=1"/>'
            '<title>SCOUT · %s · %s</title><style>%s</style></head><body>'
            '<header><h1>SCOUT</h1><span class="sub">%s · %s · 数据as-of %s · 参谋作业,Lyra 拍板</span></header>'
            '%s<footer>build scout v3.16 · quote_layer · DS 决策官 · 无证据不点名 · '
            '渲染:_render_structured/_cand_card/_md_fallback</footer></body></html>'
            % (mode.upper(), _esc(date), BRIEF_CSS, mode, _esc(date),
               ("盘初 ET %s(当日行为部分K线)" % fetchers.et_now_hm()) if mode == "morning"
               else "收盘(全日K线)", body))


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
    return bp


def emit_aether_scout(date, mode, title, body, bp, *, data=None, cross=None):
    """本机接线:落盘后 emit → 8501 store → aether OPTION(装包原版无此步,部署必接)。"""
    payload = {
        "date": date, "mode": mode, "title": title, "body": body,
        "brief_path": bp, "via": "scout_v3_15_local",
        "structured": {"_engine": cross, "ds": data} if data is not None else None,
        "liquidation_watch": bool((cross or {}).get("liquidation_watch")),
        "amc_tonight": (cross or {}).get("amc_tonight"),
        "rsi14_tape": (cross or {}).get("rsi14_tape"),
    }
    data_b = json.dumps(
        {"source": "aether", "kind": "aether_scout_brief", "payload": payload},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        GW + "/store/events", data=data_b,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            print("[scout] aether OPTION emit",
                  "ok" if 200 <= resp.status < 300 else resp.status)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print("[scout] aether emit 失败(响亮):", e)


def main():
    ap = argparse.ArgumentParser(description="Scout Agent v3(DS 决策官)")
    ap.add_argument("--mode", choices=["evening", "morning"], default="evening")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-fetch", action="store_true")
    a = ap.parse_args()
    today = fetchers.trading_date().isoformat()   # v3.12:ET 锚定,机器时区无关
    os.makedirs(os.path.join(OUT, "raw"), exist_ok=True)
    raw_path = os.path.join(OUT, "raw", today + ".json")
    # v3.16§⑦:启动横幅明示当班数据源与 feed 档
    if hasattr(fetchers, "data_plane_banner"):
        print("[scout]", fetchers.data_plane_banner())

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
        cross["earnings_movers"] = earnings_movers(payload, today)
        cross["amc_tonight"] = amc_tonight(payload, today)
        prev = load_prev_review(today)
        if prev:
            prev["rolling"] = rolling_summary(prev["date"])
            cross["prev_review"] = {"date": prev["date"], "hit": prev["hit"], "rolling": prev["rolling"]}
        ws = fetch_workstation_state()
        body = ds_call(build_trading_prompt(payload, ws, yday, cross, prev))
        data = _extract_json(body)
        if data is None:
            print("[scout] DS 未按 JSON schema 输出——晨会单降级为文本分节渲染(响亮记录)")
        else:
            data = apply_liquidity_gate(data)
        print("[scout] amc_tonight", [
            ("%s%+.1f%%" % (x.get("symbol"), x["chg_pct"])) if isinstance(x, dict) and x.get("chg_pct") is not None
            else (x.get("symbol") if isinstance(x, dict) else x)
            for x in (cross.get("amc_tonight") or [])[:12]
        ])
        print("[scout] rsi14_tape", cross.get("rsi14_tape"))
        bp = render_console("Scout 晨会交易任务单 · " + today, body, today, "morning", data, cross)
        emit_aether_scout(today, "morning", "Scout 晨会交易任务单 · " + today, body, bp,
                          data=data, cross=cross)
    else:
        # v3.13(守恒):晚班也算异动榜(全日K线,反而更准)——雷达要求点名的读数必须存在
        cross["earnings_movers"] = earnings_movers(payload, today)
        cross["amc_tonight"] = amc_tonight(payload, today)
        cross["amc_session_tape"] = amc_session_tape(cross["amc_tonight"])
        cross["amc_ah_tape"] = amc_ah_tape(cross["amc_tonight"])
        print("[scout] amc_tonight", [
            ("%s%+.1f%%" % (x.get("symbol"), x["chg_pct"])) if isinstance(x, dict) and x.get("chg_pct") is not None
            else (x.get("symbol") if isinstance(x, dict) else x)
            for x in (cross.get("amc_tonight") or [])[:12]
        ])
        print("[scout] amc_session_tape", [
            "%s%+.1f%%" % (x["symbol"], x["chg_pct"])
            for x in (cross.get("amc_session_tape") or [])[:8]
        ])
        print("[scout] amc_ah_tape", [
            x.get("ah_display") or "%s AH%+.1f%%" % (x["symbol"], x.get("vs_rth_pct") or 0)
            for x in (cross.get("amc_ah_tape") or [])[:8]
        ])
        print("[scout] rsi14_tape", cross.get("rsi14_tape"))
        # v3.16:晚班引擎名单灌进 review.watch(晨会 _engine 的 amc 可能过时/截断)
        rev = build_review(today, engine_extra={
            "amc_tonight": cross.get("amc_tonight"),
            "earnings_movers": cross.get("earnings_movers"),
        })
        if rev:
            rev["rolling"] = rolling_summary(today)
            cross["today_review"] = {
                "date": today, "hit": rev["hit"], "rolling": rev["rolling"],
                "watch_n": len(rev.get("watch") or []),
            }
            print("[scout] review.watch", [w.get("ticker") for w in (rev.get("watch") or [])])
        body = ds_call(build_evening_prompt(payload, yday, cross, rev))
        bp = render_console("Scout 晚报复盘 · " + today, body, today, "evening", None, cross)
        emit_aether_scout(today, "evening", "Scout 晚报复盘 · " + today, body, bp,
                          data=None, cross=cross)


if __name__ == "__main__":
    main()
