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
v3.16.3 = 晚班源清单:ok=true 禁伪称 SSL/缺失;赔率/FG/明日财报必须引清单条数。
v3.16.4 = 晚班源清单硬闸:显式事实行 + lint 违规则强制重写一轮(禁昨日 Polymarket SSL 幻觉)。
v3.16.5 = 晚报接 EXPANDED-GLM review/编译(8515→8501 /task/expanded · scout-review · skip Aster)。
v3.16.6 = 晨会同步 EXPANDED-GLM review/编译(与晚报同链 · 默认 SCOUT_REVIEW=expanded)。
"""
from __future__ import annotations
import argparse, datetime, html, json, os, re, sys, urllib.error, urllib.request
from collections import Counter
from pathlib import Path

import fetchers

_HERE = Path(__file__).resolve().parent
DS_BASE = os.getenv("DEEPSEEK_BASE", "https://api.deepseek.com")
DS_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DS_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
CONSOLE = os.getenv("CONSOLE_URL", "http://localhost:8610")
CONSOLE_KEY = os.getenv("CONSOLE_KEY", "").strip()
OWS = os.getenv("OWS_URL", "http://localhost:8620")
GW = os.getenv("GATEWAY_URL", "http://127.0.0.1:8501").rstrip("/")
WB = os.getenv("WORKBENCH_URL", "http://127.0.0.1:8515").rstrip("/")
OUT = os.getenv("SCOUT_OUT", os.path.dirname(os.path.abspath(__file__)))
# 晨会+晚报 review/编译:默认 EXPANDED-GLM;记忆节点禁止生产 lane
DEFAULT_REVIEW = "expanded"
SKIP_ASTER_INTEGRATE = os.getenv("SCOUT_SKIP_ASTER", "1").strip() not in (
    "0", "false", "no",
)
_FORBIDDEN_EXPANDED_NODES = frozenset({
    "workbench-b11", "cloud-glm52", "cloud-kimi", "field-particle",
})
_BAN = {"EA"}
_BAN |= {t.strip().upper() for t in os.getenv("SCOUT_BAN_TICKERS", "").split(",") if t.strip()}
_ADR_MEGA = {"BABA", "PDD", "JD", "TSM", "NVO", "BIDU", "LI", "XPEV", "NIO", "ASML", "SAP"}
_SHELL_TICKERS = {
    "SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "USO", "UNG", "TLT", "UUP",
    "VIXY", "UVXY", "FXI", "KWEB", "EWZ", "EWJ", "EEM", "YINN", "YANG",
}
_UNIVERSE_CACHE: set[str] | None = None


def load_equity_universe() -> set[str]:
    """层 A 主池 = SP500 ∪ Nasdaq-100。"""
    global _UNIVERSE_CACHE
    if _UNIVERSE_CACHE is not None:
        return _UNIVERSE_CACHE
    uni: set[str] = set()
    local = _HERE / "data" / "equity_universe.json"
    if local.is_file():
        try:
            j = json.loads(local.read_text(encoding="utf-8"))
            uni |= {str(x).upper().replace(".", "-") for x in (j.get("universe") or [])}
        except Exception as e:
            print("[scout] equity_universe.json 读失败:", e)
    sp_path = _HERE.parent / "alpha-platform" / "data" / "sp500_symbols.json"
    if sp_path.is_file():
        try:
            j = json.loads(sp_path.read_text(encoding="utf-8"))
            uni |= {str(x).upper().replace(".", "-") for x in (j.get("symbols") or [])}
        except Exception as e:
            print("[scout] sp500_symbols.json 读失败:", e)
    uni -= _SHELL_TICKERS
    _UNIVERSE_CACHE = uni
    print("[scout] 主池层A加载 %d 只(SP500∪NDX)" % len(uni))
    return uni


def in_equity_universe(ticker: str) -> bool:
    t = str(ticker or "").strip().upper().replace(".", "-")
    return bool(t) and t in load_equity_universe()


def scout_expanded_memory_node(today=None):
    """默认 scout-review-YYYY-MM-DD(按日隔离);可用 env 覆盖。"""
    env = os.getenv("SCOUT_EXPANDED_MEMORY_NODE", "").strip()
    if env:
        return env
    day = today or fetchers.trading_date().isoformat()
    return "scout-review-" + day


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


def _raw_coverage_score(raw):
    """同日多落盘时选「源最全」而非仅最新 mtime。
    2026-08-05: 1648 mtime 最新但 polymarket SSL 失败;1523 有 n=18——
    若按 mtime 取 1648,晚报会「合法」写昨日 SSL,隔夜对比失真。"""
    score = 0
    for src in (raw or {}).get("results") or []:
        if not isinstance(src, dict) or not src.get("ok"):
            continue
        n = len([x for x in (src.get("items") or []) if isinstance(x, dict)])
        if n <= 0:
            continue
        score += 10 + min(n, 50)
        # 晚报隔夜对比关键源加权
        if src.get("source") in ("polymarket_odds", "fear_greed", "earnings_calendar"):
            score += 100
    return score


def yesterday_raw(today):
    """按日期前缀取上一交易日落盘(同日多文件取覆盖度最高,mtime 次之)。
    旧实现 f < today+'.json' 有洞:'-HHMM.json' 字典序 < '.json',
    今日自己的重跑后缀文件会被当成"昨日对比"。"""
    try:
        rawdir = os.path.join(OUT, "raw")
        cand = [f for f in os.listdir(rawdir) if f.endswith(".json") and f[:10] < today]
        if not cand:
            return None
        last_day = max(f[:10] for f in cand)
        day_files = [f for f in cand if f[:10] == last_day]
        scored = []
        for f in day_files:
            path = os.path.join(rawdir, f)
            try:
                raw = json.load(open(path, encoding="utf-8"))
            except Exception:
                continue
            scored.append((
                _raw_coverage_score(raw),
                os.path.getmtime(path),
                f,
                raw,
            ))
        if not scored:
            return None
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        score, _mtime, pick, raw = scored[0]
        print("[scout] yday raw=%s coverage=%d (同日 %d 文件)"
              % (pick, score, len(scored)))
        return raw
    except Exception:
        pass
    return None


def morning_clock():
    """晨会/手动重跑时钟门。gap-and-go 只合法于盘初;临近 AMC 禁止再推今晨 BMO。"""
    hm = fetchers.et_now_hm()
    # ZoneInfo 失败时 et_now_hm 可能带后缀——只取 HH:MM
    core = str(hm).split("(")[0].strip()
    try:
        hh, mm = [int(x) for x in core.split(":")[:2]]
        minutes = hh * 60 + mm
    except Exception:
        minutes = 9 * 60 + 45
        core = "09:45"
    # 盘初窗口:开盘~10:30 ET(手册第三步 30 分钟确认后仍可短跟)
    if minutes < 10 * 60 + 30:
        phase = "open_window"
        rule = (
            "当前=盘初窗口(ET<10:30)。主菜=earnings_movers(手册第三步 gap-and-go)"
            " ∪ amc_tonight(手册第二步 run-up)。"
        )
    elif minutes < 14 * 60:
        phase = "midday"
        rule = (
            "当前=盘中重跑(ET 10:30–14:00)。仍必须恰好 3 张卡(空清单非法)。"
            "优先 amc_tonight run-up(收盘前清仓);BMO movers 若入卡须 abandon=禁止追入盘初窗口已过,"
            "只作观察/复盘卡,不得写成现价追涨指令。"
        )
    else:
        phase = "late_amc"
        rule = (
            "当前=临近收盘/AMC(ET≥14:00)。仍必须恰好 3 张卡(空清单非法)。"
            "优先今日 amc_tonight;不足 3 张用 earnings_movers 补观察卡,"
            "abandon/entry 必须写清禁止临近收盘追入;禁赌盘后;禁下周一充数。"
        )
    return {"et_hm": core, "minutes": minutes, "phase": phase, "rule": rule}


# ---- DS 决策官 prompt(v3.2 池化:大盘方向+池内提名) ----
def build_trading_prompt(raw, ws, yday, cross=None, prev=None, evening_ammo=""):
    # install 4 / v3.11:主菜随时钟——盘初 movers+AMC;盘中/临近AMC 只剩今日AMC run-up
    movers = (cross or {}).get("earnings_movers") or []
    amc = (cross or {}).get("amc_tonight") or []
    clock = (cross or {}).get("morning_clock") or morning_clock()
    return f"""你是交易台的首席决策官。现在是 ET {clock.get("et_hm") or fetchers.et_now_hm()}
(常规调度 = 9:45 ET 开盘后15分钟;交易员在美西 PST。**本轮是按当前真实钟点解读——不是假装还在 9:45**)。
时钟门 phase={clock.get("phase")} · {clock.get("rule")}
基于隔夜数据 + 当前时段可用 tape 给出清晰的分析作业
(这是给交易员参考的分析,交易员自己拍板执行,不是自动下单)。
观察宇宙(硬优先):
A. **第一优先** = S&P 500 ∪ Nasdaq-100 成分池(引擎 major_earnings / t0_pool_A)
B. 事件驱动非成分仅当层A凑不满3张且过流动性闸时才可补,小盘微盘(HE/AIXC 级)禁止占主菜
C. 海外 ADR 巨头仅迁徙/自身事件时可点
每个候选必须填 liquidity;主菜三席必须优先层A重大财报 CALL。
读数口径提醒:indices/hedge_assets 的当日行可能是盘初部分K线——若 phase≠open_window,
不得再把盘初 close_loc/gap-and-go 当「现在还能追」的入场许可。

隔夜采集:{json.dumps(raw, ensure_ascii=False)[:6000]}
工作站读数(GEX/特征):{json.dumps(ws, ensure_ascii=False) if ws else "工作站无可用实弹数据(不可达或仅合成数据),基于隔夜数据判断"}
昨日采集(对比用):{json.dumps(yday, ensure_ascii=False)[:2000] if yday else "无"}
跨资产引擎读数(确定性,判断必须引用):{json.dumps(cross, ensure_ascii=False) if cross else "无"}
昨日战绩(确定性复盘,必须引用):{json.dumps(prev, ensure_ascii=False) if prev else "无(首日或昨日无产出)"}
{evening_ammo or "昨晚报弹药:无落盘"}

★★ 今日 T+0 主菜硬锁(当前钟点直接扫 SP500∪Nasdaq 现价 tape = #1/#2/#3)★★
引擎 live_leaders(现价扫描将硬锁进三席)={json.dumps((cross or {}).get("live_leaders") or [], ensure_ascii=False)[:2200]}
引擎 major_earnings(对照·已出完不得占席)={json.dumps((cross or {}).get("major_earnings") or [], ensure_ascii=False)[:1200]}
引擎 earnings_movers(全市场对照,不得占主菜)={json.dumps(movers, ensure_ascii=False)[:600]}
引擎 amc_tonight(今日AMC未出·可注记)={json.dumps(amc, ensure_ascii=False)[:600]}
合法池 pool_A 前段=live_leaders
硬约束:
- **candidates 三卡 = live_leaders 前三**,rank=1/2/3 与现价扫描排名相同
- ticker **必须 ∈ SP500∪Nasdaq**;禁止 HE/AIXC/ROAD 等池外微盘占席
- **禁止**用已出完财报(昨AMC/今BMO)凑主菜——那是跑完的 earning call
- entry=现价可买(当前 ET 截面);收盘前清仓;禁赌盘后;禁下周一充数
- strategy.expiry 默认 0DTE;t0_exit=收盘前清仓

交易风格偏置(硬约束):交易员主菜只做 T+0 单腿 CALL,当日了结。
- candidates **direction 必须全部 = call**;strategy.type=单腿 call;到期 0DTE/最近到期;必须 t0_exit
- **candidates 禁止 PUT**(下跌 movers 进 rejected 写理由,不得用 put 占三席主菜)
- 禁止多腿组合;禁止编造权利金/报价
- PUT 仅允许出现在 hedge.legs(对冲工具),不得进 candidates
候选铁律(主菜=个股卡·空清单非法):
- **必须恰好输出 3 张 CALL 卡**,rank=1/2/3(禁止缺号、禁止空清单、禁止用 no_candidate_reason 交白卷)
- 每卡必须写 rank_reason(相对#2/#3为何排此名);每个候选必须锚定合法池条目;禁止凭训练记忆点名
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
 "candidates": [{{"rank": 1, "ticker": "", "direction": "call",
   "rank_reason": "为何排第1(相对#2/#3的优先依据)",
   "evidence": [{{"source": "edgar|fda|polymarket|indices|macro|earnings", "item": "条目摘要", "why": "为何构成驱动"}}],
   "key_levels": "该标的阻力/支撑及依据",
   "liquidity": "一句话:市值/期权活跃度为何扛得住 T+0",
   "strategy": {{"type": "单腿 call", "strike_logic": "行权价选择逻辑(不编报价)",
     "expiry": "0DTE|本周五|最近到期", "entry_condition": "入场触发条件",
     "stop": "止损条件", "abandon": "作废条件",
     "earnings_note": "5个交易日内财报:日期/BMO或AMC/采用哪条手册;无则写无",
     "t0_exit": "当日平仓纪律"}}}},
  {{"rank": 2, "ticker": "", "direction": "call", "rank_reason": "为何排第2",
   "liquidity": "", "evidence": [{{"source": "edgar|fda|polymarket|indices|macro|earnings", "item": "", "why": ""}}],
   "key_levels": "", "strategy": {{"type": "单腿 call", "strike_logic": "", "expiry": "0DTE",
     "entry_condition": "", "stop": "", "abandon": "", "earnings_note": "无", "t0_exit": ""}}}},
  {{"rank": 3, "ticker": "", "direction": "call", "rank_reason": "为何排第3",
   "liquidity": "", "evidence": [{{"source": "edgar|fda|polymarket|indices|macro|earnings", "item": "", "why": ""}}],
   "key_levels": "", "strategy": {{"type": "单腿 call", "strike_logic": "", "expiry": "0DTE",
     "entry_condition": "", "stop": "", "abandon": "", "earnings_note": "无", "t0_exit": ""}}}}],
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


def source_inventory(raw, *, today=None):
    """晚班权威源清单——防 DS 因 raw 截断而伪称 SSL/缺失(2026-08-06 判例)。"""
    today = today or fetchers.trading_date().isoformat()
    inv = []
    for src in (raw or {}).get("results") or []:
        if not isinstance(src, dict):
            continue
        name = src.get("source") or "?"
        items = [x for x in (src.get("items") or []) if isinstance(x, dict)]
        row = {
            "source": name,
            "ok": bool(src.get("ok")),
            "n": len(items),
            "error": (str(src.get("error") or "")[:160] or None),
        }
        if name == "fear_greed" and items:
            it = items[0]
            row["head"] = {
                "score": it.get("score"), "rating": it.get("rating"),
                "prev_close": it.get("prev_close"), "source": it.get("source"),
            }
        elif name == "polymarket_odds" and items:
            row["head"] = [{
                "q": (x.get("q") or "")[:120], "bucket": x.get("bucket"),
                "implied": x.get("implied"), "vol24h": x.get("vol24h"),
            } for x in items[:10]]
            row["event_n"] = sum(1 for x in items if x.get("bucket") == "event")
        elif name == "earnings_calendar" and items:
            by = Counter(x.get("date") for x in items if x.get("date"))
            row["by_date"] = dict(sorted((k, by[k]) for k in by))
            fut = [x for x in items if str(x.get("date") or "") > today]
            row["runup_n"] = len(fut)
            row["runup_sample"] = [{
                "symbol": x.get("symbol"), "date": x.get("date"),
                "when": x.get("when"), "name": (x.get("name") or "")[:40],
            } for x in fut[:24]]
        elif name in ("indices", "hedge_assets", "sectors", "commodities") and items:
            row["head"] = [{
                "name": x.get("name") or x.get("symbol"),
                "chg_pct": x.get("chg_pct"), "rsi14": x.get("rsi14"),
            } for x in items[:8]]
        elif name == "edgar_ma_8k" and items:
            row["head"] = [{
                "company": (x.get("company") or "")[:60],
                "form": x.get("form"), "filed": x.get("filed"),
            } for x in items[:6]]
        inv.append(row)
    return {"today": today, "sources": inv}


def _inv_source(inv, name):
    for s in (inv or {}).get("sources") or []:
        if s.get("source") == name:
            return s
    return None


def inventory_fact_lines(inv, yday_inv=None):
    """给 DS 的一行事实——比长 JSON 更难被忽略。"""
    lines = []
    for label, obj in (("今日", inv), ("昨日", yday_inv)):
        if not obj:
            if label == "昨日":
                lines.append("昨日:无清单(勿臆造 SSL/失败原因)")
            continue
        for name in ("polymarket_odds", "fear_greed", "earnings_calendar"):
            row = _inv_source(obj, name)
            if not row:
                lines.append("%s %s:清单无此源(勿写 SSL;可写「该日 raw 无此源」)" % (label, name))
                continue
            ok, n, err = bool(row.get("ok")), int(row.get("n") or 0), row.get("error")
            if ok and n > 0:
                # 勿在事实行写「SSL」字样——GLM 会反向抄进正文(2026-08-06 探针)
                lines.append(
                    "%s %s: ok=true n=%d — 有数据;禁止写采集失败/缺失/ok=false"
                    % (label, name, n)
                )
            else:
                err_s = str(err or "n/a")
                # error 原文可含证书字样;标签侧改写,避免诱导伪称
                if "CERTIFICATE" in err_s.upper() or "SSL" in err_s.upper():
                    err_s = "采集失败(证书/链路)"
                lines.append(
                    "%s %s: ok=%s n=%d error=%s — 仅此可写缺失"
                    % (label, name, ok, n, err_s)
                )
    return lines


def lint_evening_source_claims(body, inv, yday_inv=None):
    """对照清单抓伪称 SSL/缺失。返回违规说明列表(空=通过)。"""
    # 忽略引擎注记行,避免注记自身含「SSL」触发二次误报
    text = "\n".join(
        ln for ln in (body or "").splitlines()
        if not ln.startswith("> ⚠ 引擎注记")
    )
    bad = []
    for label, obj, prefix in (
        ("今日", inv, r"今日"),
        ("昨日", yday_inv, r"昨日"),
    ):
        row = _inv_source(obj, "polymarket_odds") if obj else None
        if row and row.get("ok") and int(row.get("n") or 0) > 0:
            pat = prefix + r".{0,80}Polymarket.{0,80}(SSL|失败|缺失|无法获取|留空|ok\s*=\s*false)"
            if re.search(pat, text, re.I | re.S):
                bad.append(
                    "%s polymarket_odds 实为 ok=true n=%d,正文却写 SSL/失败/缺失"
                    % (label, int(row.get("n") or 0))
                )
            if re.search(
                prefix + r".{0,40}采集源清单.{0,40}polymarket_odds.{0,20}ok\s*=\s*false",
                text, re.I | re.S,
            ):
                bad.append("%s 正文伪造「采集源清单 polymarket_odds ok=false」" % label)
        row_fg = _inv_source(obj, "fear_greed") if obj else None
        if row_fg and row_fg.get("ok") and int(row_fg.get("n") or 0) > 0:
            if re.search(prefix + r".{0,60}(fear_greed|恐惧贪婪|Fear).{0,40}(SSL|失败|缺失)", text, re.I | re.S):
                bad.append("%s fear_greed 实为 ok=true,正文却写失败/缺失" % label)
        row_e = _inv_source(obj, "earnings_calendar") if obj else None
        if label == "今日" and row_e and int(row_e.get("runup_n") or 0) > 0:
            if re.search(r"明日.{0,30}财报.{0,20}(缺失|未提供|无法)", text):
                bad.append("今日 earnings_calendar.runup_n>0,正文却写明日财报缺失")
    return bad


def build_evening_prompt(raw, yday, cross=None, review=None):
    # v3.16: ET 真实钟点 + §5 已出叙事 + §6 run-up 仅未来日 + watch 复盘
    # v3.16.3: 采集源清单权威——ok=true 禁伪称缺失
    # v3.16.4: 显式事实行(禁昨日 Polymarket SSL 幻觉)
    inv = source_inventory(raw)
    yday_inv = source_inventory(yday) if yday else None
    facts = "\n".join("- " + x for x in inventory_fact_lines(inv, yday_inv))
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
   盘后:引 amc_results / amc_ah_tape(Alpaca 主测;Nasdaq 为辅)——
   |盘后涨跌|≥8% 必须重点讲清(DOCS 类盘后暴动案例,禁漏);
   写「盘后 xx(feed档, HH:MM ET)」并引 source/feed_label;
   无读数则明写"盘后读数缺失",禁编数字
   (点名依据=名单+强制雷达 TEAM/DOCS,不做"谁出了结果"的侦测);
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

【采集源清单纪律·硬·v3.16.4】
- 「采集源清单」与下方「事实行」权威优先于截断 raw。ok=true 且 n>0 → 该源有数据。
- 禁止对 ok=true 的源写:SSL失败/采集失败/缺失/留空/无法提供/ok=false(含 Polymarket、fear_greed、earnings_calendar)。
- 仅当事实行写明 ok=false 或 n=0 才可写缺失,并抄写 error 原文。
- 「赔率变化」:必须写今日 n=…与昨日 n=…(见事实行),并至少引用今日 head 里 2 条;event_n>0 时点名事件桶。
- fear_greed:清单有 head 时必须写 score 与 rating(注明来源 cnn-dataviz 等)。
- 「明日日历·财报」:若 earnings_calendar.by_date 含 date>今日 或 runup_n>0,
  必须从 runup_sample 点名至少 3 个标的作 run-up 观察;禁止写「明日财报名单缺失」。
- 隔夜→今日对比:昨日 polymarket 事实行为 ok=true 时,禁止任何「昨日 SSL/失败」措辞;
  应写昨日 n=… vs 今日 n=…(能比 implied 再比,不能比就明写无法逐条对齐)。

事实行(最高权威·逐字遵守):
{facts}

复盘读数(确定性):{json.dumps(review, ensure_ascii=False) if review else "今日无晨会腿可复盘"}
跨资产引擎读数:{json.dumps(cross, ensure_ascii=False) if cross else "无"}
采集源清单(权威·今日):{json.dumps(inv, ensure_ascii=False)}
采集源清单(权威·昨日):{json.dumps(yday_inv, ensure_ascii=False) if yday_inv else "无昨日清单"}
今日采集(截断,次于清单):{json.dumps(raw, ensure_ascii=False)[:6000]}
昨日对比(截断,次于清单):{json.dumps(yday, ensure_ascii=False)[:4000] if yday else "无"}
用 markdown,严格以 ## 分节(要闻催化/赔率变化/明日日历/明日方向/风险雷达/晨会复盘与明日调优),
每节内用短段落或列表,不要糊成整段。用中文,给数字给出处,不写废话。"""


def evening_ds_with_lint(prompt, inv, yday_inv=None):
    """晚班 DS + 源清单 lint;违规则带违规条强制重写一轮。"""
    body = ds_call(prompt)
    bad = lint_evening_source_claims(body, inv, yday_inv)
    if not bad:
        return body
    print("[scout] evening source-lint FAIL → rewrite:", bad)
    fix = (
        prompt
        + "\n\n【重写指令·硬】上轮正文违反事实行,必须全文重写,不得保留违规句。\n"
        + "违规:\n- " + "\n- ".join(bad)
        + "\n上轮正文(对照,勿抄违规):\n"
        + (body or "")[:3500]
    )
    body2 = ds_call(fix)
    bad2 = lint_evening_source_claims(body2, inv, yday_inv)
    if bad2:
        print("[scout] evening source-lint still FAIL after rewrite:", bad2)
        # 仍失败则保留 rewrite 正文,但在文首钉机械注记(不静默)
        note = (
            "> ⚠ 引擎注记:源清单事实行为权威;下列伪称已由 lint 检出仍未自清:"
            + "; ".join(bad2)
            + "\n\n"
        )
        return note + body2
    return body2


def review_origin_label(*, primary_label="", expanded_meta=None):
    """标明 review/编译真实来源——以编排回执 substrate 为准。"""
    meta = expanded_meta or {}
    primary = (primary_label or "").strip().lower()
    sub = str(meta.get("substrate") or "").strip().lower()
    via = str(meta.get("via") or "")
    if meta.get("error") or via == "fallback_ds":
        return "ds(expanded失败)"
    if sub.startswith("local"):
        return "expanded-本地"
    if "glm" in sub:
        return "expanded-GLM"
    if primary == "expanded" or via.startswith("b11:"):
        return "expanded-未知"
    return "ds"


def build_morning_expanded_prompt(ds_draft, data, cross=None):
    """晨会 EXPANDED-GLM review/编译 prompt(驳回 Aster)。"""
    struct = json.dumps(data, ensure_ascii=False)[:9000] if data else (ds_draft or "")[:9000]
    eng = json.dumps({
        "morning_clock": (cross or {}).get("morning_clock"),
        "live_leaders": (cross or {}).get("live_leaders"),
        "amc_tonight": (cross or {}).get("amc_tonight"),
        "liquidation_watch": (cross or {}).get("liquidation_watch"),
    }, ensure_ascii=False)[:3500]
    return f"""你是 Scout 流水线的 review / 编译官(Grid EXPANDED · GLM-5.2 substrate),不是首席决策官。
Aster integrate 已驳回——你只做 review/编译,不扮演 Aster。
上游是 JSON 结构化晨会单(真实 ET 钟点·盘初/盘中 tape)。你输出更清晰的 Markdown 终稿给 Lyra:
- 保留个股卡结构;主菜=恰 3 张 · 默认 T+0 **单腿 CALL only**(candidates 禁止 PUT);禁多腿;禁编权利金/假 $ 报价
- 每卡必须保留 rank / rank_reason / liquidity / earnings_note / t0_exit
- **三席 = 当前钟点 SP500∪Nasdaq 现价扫描 #1/#2/#3**(禁止改票;禁止用已出完财报/观察卡替换)
- 保留 strategy.entry_condition「现价可买」;收盘前清仓;禁赌盘后;正文标明真实 ET 时刻
- SPY/QQQ 仅大盘环境;主菜=个股;synthetic GEX 不得洗成真盘
- hedge 段永不空白:保留 distribution_risk/basis/legs 或 note
- 禁止编造采集未出现的 ticker;分析作业≠下单指令
引擎截面(权威):{eng}
—— DeepSeek 结构化原稿 ——
{struct}
输出只要最终 Markdown 正文。"""


def build_evening_expanded_prompt(ds_draft, *, inv=None, yday_inv=None):
    """晚报 EXPANDED-GLM review/编译 prompt(驳回 Aster;事实行硬约束)。"""
    facts = "\n".join("- " + x for x in inventory_fact_lines(inv, yday_inv))
    return f"""你是 Scout 流水线的 review / 编译官(Grid EXPANDED · GLM-5.2 substrate),不是首席决策官。
Aster integrate 已驳回——你只做 review/编译,不扮演 Aster。
上游是晚报 Markdown 参谋作业。你输出更清晰的 Markdown 终稿给 Lyra:
- 严格保留 ## 分节:要闻催化 / 赔率变化 / 明日日历 / 明日方向 / 风险雷达 / 晨会复盘与明日调优
- 风险雷达永不空白:命中拉高出货/资金迁徙/全线下跌须点名工具;未命中明写未见
- 晨会复盘须引用确定性 review 逐腿命中;财报名单引用 earnings_calendar
- 禁止补编采集中没有的数字;禁止编造个股催化
- 分析作业≠下单指令;口径给 Lyra 拍板
- 【源清单·硬】事实行权威优先于 DS 原稿。ok=true 的源禁止写采集失败/缺失/ok=false/证书错误;
  若 DS 原稿违反对事实行,终稿必须按事实行改正,不得照抄伪称;
  若 DS 原稿已按事实行写对(如昨日 n=18 / 今日 n=24),终稿必须保留,禁止改回失败叙事。

事实行(最高权威·逐字遵守):
{facts or "- (无清单)"}

—— DeepSeek 原稿 ——
{(ds_draft or "")[:9000]}
输出只要最终 Markdown 正文。"""


def _morning_cards_markdown(data):
    """权威三席 Markdown(现价扫描硬锁)——供 EXPANDED 篡改时回封。"""
    lines = ["## 主菜 · 个股卡（恰 3 张 · SP500∪Nasdaq 现价扫描 · rank=股票卡）", ""]
    for c in (data or {}).get("candidates") or []:
        if not isinstance(c, dict):
            continue
        st = c.get("strategy") if isinstance(c.get("strategy"), dict) else {}
        lines.append("### Card #%s · %s" % (c.get("rank"), c.get("ticker")))
        lines.append("")
        lines.append("| 字段 | 内容 |")
        lines.append("|---|---|")
        lines.append("| **rank / rank_reason** | %s · %s |" % (
            c.get("rank"), (c.get("rank_reason") or "").replace("|", "/"),
        ))
        lines.append("| **direction** | %s（单腿 only） |" % (c.get("direction") or "call"))
        lines.append("| **liquidity** | %s |" % ((c.get("liquidity") or "").replace("|", "/")))
        lines.append("| **entry** | %s |" % ((st.get("entry_condition") or "").replace("|", "/")))
        lines.append("| **abandon** | %s |" % ((st.get("abandon") or "").replace("|", "/")))
        lines.append("| **earnings_note** | %s |" % ((st.get("earnings_note") or "").replace("|", "/")))
        lines.append("| **t0_exit** | %s |" % ((st.get("t0_exit") or "").replace("|", "/")))
        lines.append("")
    return "\n".join(lines)


def seal_morning_expanded(text, data):
    """EXPANDED 若改票/改成观察卡 → 用爬虫硬锁三席回封(响亮)。"""
    locked = [
        str(c.get("ticker") or "").upper()
        for c in ((data or {}).get("candidates") or [])
        if isinstance(c, dict) and c.get("ticker")
    ]
    if len(locked) != CANDIDATE_RANK_N:
        return text, False
    body = text or ""
    ok = True
    for i, sym in enumerate(locked):
        # 允许 Card #1 · ABNB / ### Card 1 · ABNB 等
        pat = re.compile(
            r"(?:Card\s*#?%d|排名\s*#%d)[^\n]{0,40}%s" % (i + 1, i + 1, re.escape(sym)),
            re.I,
        )
        if not pat.search(body):
            ok = False
            break
    # 硬禁:池外微盘冒充主菜卡
    for bad in ("HE", "AIXC", "ROAD", "ARKO"):
        if bad in locked:
            continue
        if re.search(r"Card\s*#?[123][^\n]{0,40}\b%s\b" % bad, body, re.I):
            ok = False
            break
    if ok and "禁止现价追" not in body and "观察卡" not in body:
        return body, False
    # 回封:保留前言,替换主菜段
    auth = _morning_cards_markdown(data)
    cut = re.search(r"##\s*主菜|##\s*二[^\n]*候选|###\s*Card", body)
    head = body[:cut.start()].rstrip() + "\n\n" if cut else ""
    # 丢掉错误主菜后的对冲之前
    tail_m = re.search(r"##\s*(对冲|三[^\n]*对冲|风险|数据|结论)", body)
    tail = ("\n\n" + body[tail_m.start():]) if tail_m else ""
    sealed = (
        head
        + "> ⚙ 引擎回封:EXPANDED 改票已撤销——三席=SP500∪Nasdaq 现价扫描排名。\n\n"
        + auth
        + tail
    )
    print("[scout] EXPANDED 主菜回封 →", " · ".join(
        "#%d %s" % (i + 1, s) for i, s in enumerate(locked)
    ))
    return sealed, True


def expanded_morning_review(ds_draft, data, cross=None, today=None):
    """晨会 EXPANDED-GLM:与晚报同链 POST 8515 /gateway/task/expanded → 8501。"""
    mem_node = scout_expanded_memory_node(today)
    if mem_node in _FORBIDDEN_EXPANDED_NODES:
        raise SystemExit(
            "[scout] SCOUT_EXPANDED_MEMORY_NODE=%s 禁止(生产记忆 RED LINE)"
            % mem_node
        )
    if not SKIP_ASTER_INTEGRATE:
        raise SystemExit(
            "[scout] SCOUT_SKIP_ASTER=0 已禁用——晨会 EXPANDED 默认必须驳回 Aster"
        )
    prompt = build_morning_expanded_prompt(ds_draft, data, cross)
    body = {
        "task": prompt,
        "memory_node": mem_node,
        "assets": [],
        "client_context": "scout_morning_review · expanded-GLM · skip_aster_integrate",
        "cloud_enabled": True,
        "cloud_backend": "glm52_cloud",
        "skip_aster_integrate": True,
    }
    url = WB + "/gateway/task/expanded"
    try:
        r = _http(url, body, timeout=420)
        final = (r.get("final") or r.get("content") or "").strip()
        if not final:
            raise RuntimeError("expanded empty final keys=%s" % list(r.keys())[:12])
        final, sealed = seal_morning_expanded(final, data)
        prov = r.get("provenance") or {}
        meta = {
            "substrate": r.get("substrate"),
            "orchestrator": (prov.get("orchestrator") or r.get("orchestrator")),
            "envelope": prov.get("envelope_summary"),
            "memory_node": mem_node,
            "via": "b11:/gateway/task/expanded",
            "cloud_backend": r.get("cloud_backend") or "glm52_cloud",
            "cards_sealed": sealed,
        }
        meta["review_origin"] = review_origin_label(
            primary_label="expanded", expanded_meta=meta
        )
        print(
            "[scout] 晨会 EXPANDED-GLM review/编译完成 %d 字符 origin=%s substrate=%s sealed=%s"
            % (len(final), meta.get("review_origin"), meta.get("substrate"), sealed)
        )
        return {"text": final, "meta": meta}
    except Exception as e:
        print("[scout] 晨会 EXPANDED-GLM review 失败(%s)→ 降级用 DS 原稿(响亮)" % e)
        meta = {
            "error": str(e),
            "via": "fallback_ds",
            "memory_node": mem_node,
        }
        meta["review_origin"] = review_origin_label(
            primary_label="ds", expanded_meta=meta
        )
        return {"text": ds_draft, "meta": meta}


def expanded_evening_review(ds_draft, *, inv=None, yday_inv=None, today=None):
    """b11 EXPANDED-GLM:POST 8515 /gateway/task/expanded → 8501。

    memory_node=scout-review-YYYY-MM-DD(默认按日隔离),绝不写 workbench-b11 / cloud-*。
    cloud_backend=glm52_cloud 强制 EXPANDED-GLM(非本地 substrate)。
    """
    mem_node = scout_expanded_memory_node(today)
    if mem_node in _FORBIDDEN_EXPANDED_NODES:
        raise SystemExit(
            "[scout] SCOUT_EXPANDED_MEMORY_NODE=%s 禁止(生产记忆 RED LINE)"
            % mem_node
        )
    if not SKIP_ASTER_INTEGRATE:
        raise SystemExit(
            "[scout] SCOUT_SKIP_ASTER=0 已禁用——晚报 EXPANDED 默认必须驳回 Aster"
        )
    prompt = build_evening_expanded_prompt(ds_draft, inv=inv, yday_inv=yday_inv)
    body = {
        "task": prompt,
        "memory_node": mem_node,
        "assets": [],
        "client_context": "scout_evening_review · expanded-GLM · skip_aster_integrate",
        "cloud_enabled": True,
        "cloud_backend": "glm52_cloud",
        "skip_aster_integrate": True,
    }
    url = WB + "/gateway/task/expanded"

    def _call_expanded(task_text):
        payload = dict(body)
        payload["task"] = task_text
        r = _http(url, payload, timeout=420)
        final = (r.get("final") or r.get("content") or "").strip()
        if not final:
            raise RuntimeError("expanded empty final keys=%s" % list(r.keys())[:12])
        return final, r

    def _reject_to_ds(reason, r=None, bad=None):
        print("[scout] EXPANDED 驳回→ DS 原稿(%s)" % reason)
        meta = {
            "error": reason,
            "via": "fallback_ds",
            "memory_node": mem_node,
            "lint_violations": bad or [],
            "substrate": (r or {}).get("substrate"),
        }
        meta["review_origin"] = review_origin_label(
            primary_label="ds", expanded_meta=meta
        )
        return {"text": ds_draft, "meta": meta}

    def _expanded_usable(final, r):
        sub = str((r or {}).get("substrate") or "")
        if "_error" in sub or sub.endswith("error"):
            return False, "substrate_error:%s" % sub
        if len((final or "").strip()) < 400:
            return False, "expanded_too_short:%d" % len((final or "").strip())
        return True, ""

    try:
        final, r = _call_expanded(prompt)
        ok, why = _expanded_usable(final, r)
        if not ok:
            return _reject_to_ds(why, r)
        bad = lint_evening_source_claims(final, inv, yday_inv)
        if bad:
            print("[scout] EXPANDED 终稿 source-lint FAIL → rewrite:", bad)
            fix = (
                prompt
                + "\n\n【重写指令·硬】上轮终稿违反事实行,必须全文重写,不得保留违规句。"
                "须保留全部 ## 分节与关键数字,禁止只回一句道歉。\n"
                + "违规:\n- " + "\n- ".join(bad)
                + "\n上轮终稿(对照,勿抄违规):\n"
                + final[:3500]
            )
            final, r = _call_expanded(fix)
            ok, why = _expanded_usable(final, r)
            if not ok:
                return _reject_to_ds("rewrite_" + why, r, bad)
            bad = lint_evening_source_claims(final, inv, yday_inv)
            if bad:
                print("[scout] EXPANDED source-lint still FAIL after rewrite:", bad)
                if not lint_evening_source_claims(ds_draft, inv, yday_inv):
                    return _reject_to_ds(
                        "expanded_lint_reject:" + "; ".join(bad), r, bad
                    )
                final = (
                    "> ⚠ 引擎注记:EXPANDED 终稿事实行未自清 · "
                    + "; ".join(bad)
                    + "\n\n"
                    + final
                )
        prov = r.get("provenance") or {}
        meta = {
            "substrate": r.get("substrate"),
            "orchestrator": (prov.get("orchestrator") or r.get("orchestrator")),
            "envelope": prov.get("envelope_summary"),
            "memory_node": mem_node,
            "via": "b11:/gateway/task/expanded",
            "cloud_backend": r.get("cloud_backend") or "glm52_cloud",
            "lint_violations": bad,
        }
        meta["review_origin"] = review_origin_label(
            primary_label="expanded", expanded_meta=meta
        )
        print(
            "[scout] EXPANDED-GLM review/编译完成 %d 字符 origin=%s substrate=%s"
            % (len(final), meta.get("review_origin"), meta.get("substrate"))
        )
        return {"text": final, "meta": meta}
    except Exception as e:
        print("[scout] EXPANDED-GLM review 失败(%s)→ 降级用 DS 原稿(响亮)" % e)
        meta = {
            "error": str(e),
            "via": "fallback_ds",
            "memory_node": mem_node,
        }
        meta["review_origin"] = review_origin_label(
            primary_label="ds", expanded_meta=meta
        )
        return {"text": ds_draft, "meta": meta}


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


def _next_monday_iso(today):
    d = datetime.date.fromisoformat(today)
    # Mon=0 … Fri=4; 距离「下一个周一」(含「下下周一」若今天已是周一)
    delta = (7 - d.weekday()) % 7
    if delta == 0:
        delta = 7
    return (d + datetime.timedelta(days=delta)).isoformat()


def _earnings_cal_items(payload):
    for src in payload.get("results", payload.get("sources", [])):
        if src.get("source") == "earnings_calendar":
            return list(src.get("items") or [])
    return []


def earnings_call_window(payload, today):
    """本周五 AMC + 下周一 BMO/AMC——晨会主菜硬名单(手册第二步 run-up)。

    堵:用已出结果的今日 BMO 异动/无财报腿(BABA)冒充 earnings CALL。
    """
    mon = _next_monday_iso(today)
    fri_amc, mon_bmo, mon_amc = [], [], []
    for it in _earnings_cal_items(payload):
        if not isinstance(it, dict):
            continue
        sym = (it.get("symbol") or "").upper().replace(".", "-")
        if not re.fullmatch(r"[A-Z]{1,5}", sym):
            continue
        d = str(it.get("date") or "")[:10]
        when = (it.get("when") or "").lower()
        if d == today and "after" in when:
            fri_amc.append(sym)
        elif d == mon and "pre" in when:
            mon_bmo.append(sym)
        elif d == mon and "after" in when:
            mon_amc.append(sym)
    # 去重保序
    def _uniq(xs):
        out, seen = [], set()
        for x in xs:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out
    return {
        "today": today,
        "next_monday": mon,
        "friday_amc": _uniq(fri_amc)[:20],
        "monday_bmo": _uniq(mon_bmo)[:20],
        "monday_amc": _uniq(mon_amc)[:20],
        "pool": _uniq(fri_amc + mon_bmo + mon_amc)[:40],
    }


def load_evening_ammo(today):
    """昨晚报「明日日历/方向」弹药——晨会必须对齐,不另发明主菜。"""
    try:
        yd = fetchers.prev_trading_day(datetime.date.fromisoformat(today)).isoformat()
    except Exception:
        return ""
    bdir = os.path.join(OUT, "briefs")
    for name in (
        "%s-evening-final-expanded.md" % yd,
        "%s-evening-final.md" % yd,
        "%s-evening.md" % yd,
    ):
        p = os.path.join(bdir, name)
        if not os.path.isfile(p):
            continue
        try:
            text = open(p, encoding="utf-8").read()
        except OSError:
            continue
        # 截取明日日历/方向相关节
        chunks = []
        for marker in ("## 明日日历", "## 明日方向", "## 明日值得盯", "### 明日及以后财报"):
            i = text.find(marker)
            if i >= 0:
                chunks.append(text[i:i + 1800])
        if not chunks:
            chunks.append(text[:2500])
        return ("昨晚报弹药(%s):\n" % name) + "\n---\n".join(chunks)[:4500]
    return ""


def _mcap_num(txt):
    t = (txt or "").replace(",", "").replace("$", "").strip()
    if not t:
        return 0.0
    mult = 1.0
    if t[-1:].upper() in ("T", "B", "M", "K"):
        mult = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}[t[-1].upper()]
        t = t[:-1]
    try:
        return float(t) * mult
    except ValueError:
        return 0.0


def major_earnings_calls(payload, today):
    """重大财报 CALL 爬虫:earnings_calendar ∩ 层A(SP500∪NDX)。
    窗=昨AMC(含 time-not-supplied)+今BMO+今AMC;按市值排序。"""
    uni = load_equity_universe()
    yd = fetchers.prev_trading_day(datetime.date.fromisoformat(today)).isoformat()
    rows = []
    for it in _earnings_cal_items(payload):
        if not isinstance(it, dict):
            continue
        sym = (it.get("symbol") or "").upper().replace(".", "-")
        if not re.fullmatch(r"[A-Z]{1,5}", sym) or sym not in uni or sym in _BAN:
            continue
        d = str(it.get("date") or "")[:10]
        when = (it.get("when") or "").lower()
        tag = None
        if d == yd and ("after" in when or "not-supplied" in when or not when.strip()):
            tag = "昨日AMC" if "after" in when else "昨日财报"
        elif d == today and ("pre" in when or "bmo" in when):
            tag = "今日BMO"
        elif d == today and "after" in when:
            tag = "今日AMC"
        if not tag:
            continue
        rows.append({
            "symbol": sym,
            "when": tag,
            "date": d,
            "name": (it.get("name") or "")[:40],
            "marketCap": it.get("marketCap"),
            "mcap": _mcap_num(it.get("marketCap")),
            "tier": "A",
        })
    # 去重保市值序
    best = {}
    for r in rows:
        prev = best.get(r["symbol"])
        if not prev or r["mcap"] > prev["mcap"]:
            best[r["symbol"]] = r
    out = sorted(best.values(), key=lambda x: -x["mcap"])
    # tape 盖章(有界)
    syms = [x["symbol"] for x in out[:24]]
    snaps = {}
    if syms and hasattr(fetchers, "quote_layer"):
        snaps = fetchers.quote_layer.snapshot(syms) or {}
    for x in out:
        s = snaps.get(x["symbol"]) or {}
        if s.get("chg_pct") is not None:
            x["chg_pct"] = s.get("chg_pct")
            x["close_loc"] = s.get("close_loc")
            x["rsi14"] = s.get("rsi14")
    return out[:20]


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
    # 80→120:热日中盘(DOCS~$4B)否则仍会被榜首巨头挤出(与日历热日解封配套)
    out = out[:120]
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


# 强制入盘后雷达:TEAM(日历截断案例)+DOCS(盘后+60%~+68% 案例;日历常漏仍须留痕)
AMC_AH_FORCE = ("TEAM", "DOCS")


def _amc_sym_list(amc_syms, force=None):
    force = AMC_AH_FORCE if force is None else force
    syms, seen = [], set()
    for s in list(force) + list(amc_syms or []):
        u = _amc_row_sym(s)
        if not u or u in seen or not re.fullmatch(r"[A-Z]{1,5}", u):
            continue
        seen.add(u)
        syms.append(u)
    return syms


def amc_session_tape(amc_syms, *, force=None, limit=12):
    """今晚 AMC 名单的「常规时段」tape(Alpaca 日线)——供晚报逐票复盘。
    口径:RTH 收盘价,不是盘后财报反应价。晚报另有 amc_ah_tape。"""
    force = AMC_AH_FORCE if force is None else force
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


def amc_ah_tape(amc_syms, *, force=None, limit=12):
    """今日 AMC 盘后 tape——经 quote_layer.snapshot(v3.16§⑦ / Alpaca)。
    强制含 DOCS(盘后大涨案例)+TEAM;有 ah_price 才入表;
    展示口径=「盘后 xx(feed档, HH:MM ET)」;无则 DS 写读数缺失。"""
    force = AMC_AH_FORCE if force is None else force
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


CANDIDATE_RANK_N = 3


def _amc_syms(cross):
    out = []
    for a in (cross or {}).get("amc_tonight") or []:
        if isinstance(a, dict) and a.get("symbol"):
            out.append(str(a["symbol"]).upper())
        elif isinstance(a, str):
            out.append(a.upper())
    return out


def _finished_earnings_syms(cross):
    """已出完的财报(昨AMC/今BMO)——盘中/临近禁止拿来占主菜。"""
    out = set()
    for m in (cross or {}).get("major_earnings") or []:
        if not isinstance(m, dict):
            continue
        when = str(m.get("when") or "")
        sym = str(m.get("symbol") or "").upper()
        if not sym:
            continue
        if "昨日" in when or when == "今日BMO":
            out.add(sym)
    for m in (cross or {}).get("earnings_movers") or []:
        if not isinstance(m, dict):
            continue
        when = str(m.get("when") or "")
        sym = str(m.get("symbol") or "").upper()
        if sym and ("昨日" in when or "BMO" in when.upper() or "今日BMO" in when):
            out.add(sym)
    return out


def live_universe_leaders(cross=None, *, top_n=12, et_hm=None, phase=None):
    """当前钟点扫 SP500∪Nasdaq → 按「今日开盘后」动能排 CALL(主菜真源)。

    盘中/临近:禁「相对昨收大涨但盘中已熄火」——那是隔夜/昨天涨完的。
    排序键=intraday(今开→现价),不是 day chg(昨收→现价)。
    """
    uni_set = load_equity_universe()
    uni = sorted(uni_set)
    clock = (cross or {}).get("morning_clock") or {}
    et_hm = et_hm or clock.get("et_hm") or fetchers.et_now_hm()
    phase = phase or clock.get("phase") or "open_window"
    print("[scout] 现价扫描 SP500∪NDX n=%d · ET %s · phase=%s · 键=今开后intraday"
          % (len(uni), et_hm, phase))
    snaps = {}
    if hasattr(fetchers, "quote_layer"):
        snaps = fetchers.quote_layer.snapshot(uni, with_rsi=False) or {}
    finished = _finished_earnings_syms(cross)
    amc_set = set(_amc_syms(cross)) & uni_set
    rows = []
    skipped_ran = 0
    for sym, s in snaps.items():
        if not isinstance(s, dict):
            continue
        u = str(sym).upper()
        if u in _BAN or u in _SHELL_TICKERS:
            continue
        if u in finished:
            continue
        o, c, day = s.get("open"), s.get("close"), s.get("chg_pct")
        if o is None or c is None or not o:
            continue
        try:
            o, c = float(o), float(c)
        except (TypeError, ValueError):
            continue
        intra = (c / o - 1.0) * 100.0
        # 昨收:由 day chg 反推(Alpaca dailyBar)
        prev = None
        gap = None
        if day is not None and c and day != -100:
            try:
                prev = c / (1.0 + float(day) / 100.0)
                if prev > 0:
                    gap = (o / prev - 1.0) * 100.0
            except (TypeError, ValueError, ZeroDivisionError):
                prev, gap = None, None
        close_loc = s.get("close_loc")
        loc = float(close_loc) if close_loc is not None else 0.0

        # —— 已涨完过滤(盘中/临近硬闸)——
        if phase != "open_window":
            # CALL 必须全日仍绿——低开反弹的「假今开后涨」不进(如大跌日死猫跳)
            if day is None or day <= 0:
                continue
            # 隔夜跳空已吃掉大部分涨幅 → 昨天/盘前涨完,禁止占席
            if gap is not None and gap >= 4.0 and intra < gap:
                skipped_ran += 1
                continue
            # 今开后没在涨 → 不是「现在」可买 CALL
            if intra < 1.0:
                continue
            # 相对昨收大涨但盘中走弱/走平 → 余波,不进
            if day >= 8.0 and intra < 2.5:
                skipped_ran += 1
                continue
            score = intra * 10.0 + loc * 3.0
        else:
            # 盘初:允许 gap-and-go(日涨可作为辅助),但仍要求今开后非明显派发
            if day is None or day <= 0:
                continue
            if intra < -1.0:
                continue
            score = float(day) * 6.0 + max(intra, 0.0) * 8.0 + loc * 2.0

        if u in amc_set:
            score += 3.0
        rows.append({
            "symbol": u,
            "chg_pct": day,
            "intra_pct": round(intra, 2),
            "gap_pct": round(gap, 2) if gap is not None else None,
            "close_loc": close_loc,
            "rsi14": s.get("rsi14"),
            "open": o,
            "close": c,
            "tape_flag": s.get("tape_flag"),
            "source": s.get("source") or "alpaca",
            "et_hm": str(et_hm).split("(")[0].strip(),
            "finished_earnings": False,
            "today_amc": u in amc_set,
            "_score": score,
        })
    rows.sort(key=lambda r: (
        -(r.get("intra_pct") or 0),
        -(r.get("close_loc") or 0),
        -(r.get("chg_pct") or 0),
    ))
    if skipped_ran:
        print("[scout] 剔除隔夜/已涨完 %d 只(禁用昨收涨幅冒充现价)" % skipped_ran)
    out = rows[:top_n]
    for r in out[:CANDIDATE_RANK_N]:
        if r.get("rsi14") is not None:
            continue
        try:
            closes = fetchers.quote_layer.bars(r["symbol"], limit=60) or []
            if len(closes) >= 15 and hasattr(fetchers, "_rsi14"):
                r["rsi14"] = fetchers._rsi14(closes)
        except Exception:
            pass
    return out


def _t0_earnings_pool(cross, phase=None):
    """合法池=现价 SPX∪NDX 扫描序(+层A全集后备)。"""
    del phase
    uni = load_equity_universe()
    pool = []
    for m in (cross or {}).get("live_leaders") or []:
        if isinstance(m, dict) and m.get("symbol"):
            pool.append(str(m["symbol"]).upper())
    pool.extend(sorted(uni))
    out, seen = [], set()
    for x in pool:
        x = (x or "").upper().replace(".", "-")
        if not x or x in seen or x in _BAN or x in _SHELL_TICKERS:
            continue
        if x not in uni and x not in _ADR_MEGA:
            continue
        seen.add(x)
        out.append(x)
    return out


def _card_from_live(meta, rank, phase="open_window"):
    """现价 SPX∪NDX 扫描 → #rank 股票卡(键=今开后intraday)。"""
    del phase
    sym = str(meta.get("symbol") or "").upper()
    intra = meta.get("intra_pct")
    gap = meta.get("gap_pct")
    day = meta.get("chg_pct")
    loc = meta.get("close_loc")
    rsi = meta.get("rsi14")
    et = meta.get("et_hm") or "?"
    intra_txt = (" 今开后%+.2f%%" % intra) if intra is not None else ""
    gap_txt = (" 跳空%+.2f%%" % gap) if gap is not None else ""
    day_txt = (" 相对昨收%+.2f%%" % day) if day is not None else ""
    loc_txt = (" close_loc=%.2f" % loc) if loc is not None else ""
    rsi_txt = (" RSI14=%s" % rsi) if rsi is not None else ""
    amc = meta.get("today_amc")
    entry = "现价可买 · 今开后仍在涨(ET %s) · 收盘前清仓" % et
    if amc:
        entry = "今日AMC run-up · 今开后动能确认 · 收盘前清仓(ET %s)" % et
    note = "今日AMC · 未出" if amc else "无(非隔夜/已涨完占席)"
    reason = (
        "SP500∪NDX 今开后扫描 #%d · ET %s · %s%s%s%s%s · 单腿 CALL"
        % (rank, et, sym, intra_txt, loc_txt, rsi_txt, gap_txt)
    )
    return {
        "ticker": sym,
        "rank": rank,
        "direction": "call",
        "rank_reason": reason,
        "liquidity": "层A(SP500∪Nasdaq)现价成分",
        "evidence": [{
            "source": "live_universe",
            "item": "%s ET%s 今开后%s%s%s%s%s source=%s" % (
                sym, et, intra_txt, gap_txt, day_txt, loc_txt, rsi_txt,
                meta.get("source") or "alpaca",
            ),
            "why": "排序键=今开→现价(禁用昨收涨幅把隔夜涨完的排进来)·硬锁 #%d" % rank,
        }],
        "key_levels": "今日开盘/高低点(Alpaca 现价截面)",
        "strategy": {
            "type": "单腿 call",
            "strike_logic": "ATM",
            "expiry": "0DTE",
            "entry_condition": entry,
            "stop": "破今日低点或今开后动量断裂",
            "abandon": "收盘前未清仓 / 赌盘后 / 已确认隔夜涨完",
            "earnings_note": note,
            "t0_exit": "收盘前清仓",
        },
        "_from_live_universe": True,
    }


def force_candidates_call_only(data):
    """主菜禁 PUT:put 腿踢进 rejected,腾位给 CALL 补位。"""
    if not isinstance(data, dict):
        return data
    keep, kicked = [], []
    for c in data.get("candidates") or []:
        if not isinstance(c, dict):
            continue
        d = str(c.get("direction") or "call").lower()
        st = c.get("strategy") if isinstance(c.get("strategy"), dict) else {}
        typ = str((st or {}).get("type") or "").lower()
        if d == "put" or "put" in typ:
            kicked.append(str(c.get("ticker") or "?").upper())
            continue
        c = dict(c)
        c["direction"] = "call"
        st = dict(st or {})
        st["type"] = "单腿 call"
        c["strategy"] = st
        keep.append(c)
    if kicked:
        rej = list(data.get("rejected") or [])
        have = {str(r.get("ticker") or "").upper() for r in rej if isinstance(r, dict)}
        for t in kicked:
            if t in have:
                continue
            rej.append({
                "ticker": t,
                "reason": "主菜禁 PUT(只做 T+0 单腿 CALL)——看空腿不进三席",
            })
            print("[scout] 剔除 PUT 主菜:", t)
        data["rejected"] = rej
    data["candidates"] = keep
    return data


def ensure_candidates(data, cross, phase="open_window"):
    """铁律:三席 = 当前钟点 SP500∪Nasdaq 现价扫描 #1/#2/#3(禁已出完财报凑席)。"""
    if not isinstance(data, dict):
        return data
    data = force_candidates_call_only(data)
    leaders = list((cross or {}).get("live_leaders") or [])
    if len(leaders) < CANDIDATE_RANK_N:
        leaders = live_universe_leaders(cross, top_n=12)
        cross["live_leaders"] = leaders
    ds_by = {
        str(c.get("ticker") or "").upper(): c
        for c in (data.get("candidates") or [])
        if isinstance(c, dict) and c.get("ticker")
    }
    cands = []
    for i, meta in enumerate(leaders[:CANDIDATE_RANK_N]):
        rank = i + 1
        card = _card_from_live(meta, rank, phase=phase)
        ds = ds_by.get(card["ticker"])
        if ds and str(ds.get("rank_reason") or "").strip():
            card["rank_reason"] = (
                "现价扫描#%d · " % rank
            ) + str(ds.get("rank_reason")).strip()[:180]
        cands.append(card)
        print("[scout] 主菜硬锁今开后扫描 #%d %s intra=%s gap=%s" % (
            rank, card["ticker"], meta.get("intra_pct"), meta.get("gap_pct"),
        ))
    live_set = {c["ticker"] for c in cands}
    rej = list(data.get("rejected") or [])
    for t in ds_by:
        if t in live_set:
            continue
        rej.append({
            "ticker": t,
            "reason": "非 SP500∪NDX 现价扫描前三——席位让给当前钟点 tape",
        })
    # 已出完财报若仍被扫进(后备)→ rejected 留痕
    for c in cands:
        if c.get("ticker") in _finished_earnings_syms(cross):
            print("[scout] WARN 现价扫描后备仍含已出完财报:", c.get("ticker"))
    data["rejected"] = rej
    data["candidates"] = cands[:CANDIDATE_RANK_N]
    if data["candidates"]:
        data["no_candidate_reason"] = ""
        tick = " · ".join(
            "#%s %s" % (c.get("rank"), c.get("ticker"))
            for c in data["candidates"]
        )
        et = ((cross or {}).get("morning_clock") or {}).get("et_hm") or fetchers.et_now_hm()
        data["conclusion"] = (
            "主菜三席=SP500∪Nasdaq 现价扫描(ET %s) %s。"
            "入场按各卡现价可买,收盘前清仓,禁赌盘后。"
            "已出完财报(昨AMC/今BMO)不占主菜。"
        ) % (et, tick)
    return data


def _assign_ranks(cands, pool=None):
    """强制 rank=1..3;缺字段补占位;pool 非空时剔除池外(保留财报注记可补)。"""
    pool_set = {str(x).upper() for x in (pool or []) if x}
    out = []
    for c in (cands or []):
        if not isinstance(c, dict):
            continue
        c = dict(c)
        ticker = str(c.get("ticker") or "").upper()
        st = c.get("strategy") if isinstance(c.get("strategy"), dict) else {}
        st = dict(st)
        note = str(st.get("earnings_note") or "").strip()
        if pool_set and ticker not in pool_set:
            print("[scout] 剔除非今日T+0财报池候选:", ticker)
            continue
        if len(out) >= CANDIDATE_RANK_N:
            break
        c["rank"] = len(out) + 1
        if not str(c.get("rank_reason") or "").strip():
            c["rank_reason"] = (
                "【待补排名理由】相对其余候选的优先依据未写清——按输出顺序暂列 #%d"
                % c["rank"]
            )
            print("[scout] rank_reason 缺失 → 占位 #%d %s" % (c["rank"], ticker))
        if not str(c.get("liquidity") or "").strip():
            c["liquidity"] = "【待补流动性】须说明市值/期权深度为何扛得住 T+0"
            print("[scout] liquidity 缺失 → 占位 #%d %s" % (c["rank"], ticker))
        if not note:
            st["earnings_note"] = "无"
        c["strategy"] = st
        out.append(c)
    return out


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


def _fix_raw_newlines_in_json_strings(s):
    """DS 常在 JSON 字符串里塞裸换行 → json.loads 失败;转义为 \\n。"""
    out, in_str, esc = [], False, False
    for ch in s or "":
        if in_str:
            if esc:
                out.append(ch)
                esc = False
                continue
            if ch == "\\":
                out.append(ch)
                esc = True
                continue
            if ch == '"':
                in_str = False
                out.append(ch)
                continue
            if ch == "\n":
                out.append("\\n")
                continue
            if ch == "\r" or (ord(ch) < 32):
                continue
            out.append(ch)
        else:
            if ch == '"':
                in_str = True
            out.append(ch)
    return "".join(out)


def _extract_json(text):
    """从 DS 回复抽 JSON(容忍围栏/裸换行/尾截断);抽不出返回 None,上游响亮降级。

    2026-08-07:晨会 JSON 在 data_gaps.handling 中途截断 → 无 morning.json →
    8620 仍停在昨日。此处尽量抢救到完整顶层字段。
    """
    t = text or ""
    i = t.find("{")
    if i < 0:
        return None
    blob = _fix_raw_newlines_in_json_strings(t[i:])
    j = blob.rfind("}")
    if j > 0:
        try:
            return json.loads(blob[: j + 1])
        except Exception:
            pass
    # 截断抢救:砍掉未完成的 data_gaps/conclusion 尾,闭合成可解析对象
    for marker in ('"data_gaps"', '"conclusion"'):
        cut = blob.find(marker)
        if cut <= 0:
            continue
        prefix = blob[:cut].rstrip().rstrip(",")
        for tail in (
            ',\n  "data_gaps": [],\n  "conclusion": "(DS JSON 截断修复)"\n}',
            '\n}',
        ):
            try:
                obj = json.loads(prefix + tail)
                if isinstance(obj, dict) and (obj.get("candidates") or obj.get("macro")):
                    print("[scout] _extract_json 截断抢救成功 marker=%s" % marker)
                    return obj
            except Exception:
                continue
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


def _short(x, n=96):
    s = " ".join(str(x if x is not None else "").split())
    if len(s) <= n:
        return s
    return s[: max(0, n - 1)] + "…"


def _cand_card(c, tag, badge="SCOUT"):
    """卡面:排名+rank_reason 主区必显;主菜 pill 只 CALL。"""
    d = (c.get("direction") or "call").lower()
    if badge == "SCOUT":
        d = "call"  # 主菜渲染硬锁 CALL
    st = c.get("strategy") or {}
    evs = "".join(
        '<div class="ev"><div class="src">%s</div><div>%s</div><div class="why">%s</div></div>'
        % (_esc(e.get("source", "")), _esc(e.get("item", "")), _esc(e.get("why", "")))
        for e in (c.get("evidence") or [])) or '<div class="ev">(无证据条目——按铁律本卡不应存在)</div>'
    rank = c.get("rank")
    rank_badge = ("#%s" % rank) if rank not in (None, "") else ""
    rows = []
    if rank_badge:
        rows.append(("排名", rank_badge))
    if c.get("rank_reason"):
        rows.append(("排名理由", _short(c.get("rank_reason"), 140)))
    rows += [("形态", "单腿 call" if badge == "SCOUT" else st.get("type")),
             ("行权价逻辑", st.get("strike_logic")),
             ("到期", st.get("expiry")), ("入场条件", _short(st.get("entry_condition"), 80)),
             ("止损", _short(st.get("stop"), 60)), ("作废条件", _short(st.get("abandon"), 60)),
             ("财报", _short(st.get("earnings_note"), 72)),
             ("流动性", _short(c.get("liquidity"), 72)),
             ("T+0 平仓", _short(st.get("t0_exit"), 48)),
             ("关键位", _short(c.get("key_levels"), 72))]
    kvs = "".join(
        '<div class="kv"><b>%s</b><span>%s</span></div>' % (l, _esc(v))
        for l, v in rows if v)
    extra = []
    lc = c.get("liquidity_check") or {}
    if lc:
        extra.append('<div class="ev"><div class="src">liquidity_check</div><div>%s</div></div>'
                     % _esc("$%.2fB · %s" % (lc["mcap_b"], lc.get("verdict", ""))
                            if lc.get("mcap_b") is not None else lc.get("verdict")))
    tc = c.get("tape_check") or {}
    if tc:
        extra.append('<div class="ev"><div class="src">tape_check</div><div>%s</div></div>'
                     % _esc("RSI %s · %+.2f%% · %s" % (
                         tc.get("rsi14") if tc.get("rsi14") is not None else "—",
                         tc.get("chg_pct") or 0, tc.get("verdict") or "")))
    details = "".join(extra) + evs
    badge_txt = ("%s %s" % (badge, tag)).strip()
    if rank_badge and badge == "SCOUT":
        badge_txt = ("%s %s %s" % (badge, rank_badge, tag)).strip()
    return ('<div class="card"><span class="badge">%s</span>'
            '<div class="tick"><span class="sym">%s</span><span class="pill%s">%s</span></div>%s'
            '<details><summary>展开解析(证据出处)</summary>%s</details></div>'
            % (_esc(badge_txt), _esc((c.get("ticker") or "?").upper()),
               " put" if d == "put" else "", d.upper(), kvs, details))


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
               % (_esc(_short(m.get("logic", ""), 140)),
                  _esc(_short(m.get("key_levels", ""), 120))))
    if cands:
        ordered = sorted(
            [c for c in cands if isinstance(c, dict)],
            key=lambda x: int(x.get("rank") or 99),
        )
        out.append('<section><h2>二 · 池内候选(排名1–3 · T+0 单腿 CALL)</h2>%s</section>'
                   % "".join(_cand_card(c, date) for c in ordered))
    else:
        full = str(data.get("no_candidate_reason") or "").strip()
        # sample v38: empty 只一行;长理由进折叠,禁止糊墙
        block = '<div class="empty">今日池内无事件驱动候选</div>'
        if full:
            block += ('<details><summary>空仓理由</summary>'
                      '<div class="card"><p>%s</p></div></details>' % _esc(full))
        out.append('<section><h2>二 · 池内候选(默认形态:T+0 单腿 CALL)</h2>%s</section>' % block)
    rej = data.get("rejected") or []
    if rej:
        out.append('<section><h2>二·附 · 已淘汰候选(漏斗可审)</h2><div class="card">%s</div></section>'
                   % "".join('<div class="kv"><b>%s</b><span>%s</span></div>'
                             % (_esc(r.get("ticker")), _esc(_short(r.get("reason"), 72)))
                             for r in rej[:8]))
    hcard = ('<div class="card"><div class="kv"><b>风险评估</b>'
             '<span style="color:%s">%s</span></div>'
             '<div class="kv"><b>依据</b><span>%s</span></div>%s</div>'
             % (rc, _esc(risk), _esc(_short(hd.get("basis", ""), 120)),
                ('<div class="kv"><b>说明</b><span>%s</span></div>'
                 % _esc(_short(hd.get("note"), 100))) if hd.get("note") else ""))
    out.append('<section><h2>三 · 对冲(拉高出货/黑天鹅雷达)</h2>%s%s</section>'
               % (hcard, "".join(_cand_card(l, date, "HEDGE") for l in (hd.get("legs") or []))))
    if gaps:
        out.append('<section><h2>四 · 数据缺失与矛盾标注</h2><div class="card"><table>'
                   '<tr><th>项目</th><th>状态</th><th>处理</th></tr>%s</table></div></section>'
                   % "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
                             % (_esc(_short(g.get("item"), 40)),
                                _esc(_short(g.get("status"), 24)),
                                _esc(_short(g.get("handling"), 60)))
                             for g in gaps[:6]))
    if data.get("conclusion"):
        out.append('<section><h2>五 · 结论</h2><div class="card">%s</div></section>'
                   % _esc(_short(data.get("conclusion"), 160)))
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
    # tape flags 全量会糊成墙——主卡只留指数/关键对冲,其余折叠不进主区
    _tf = cross.get("tape_flags") or {}
    _tf_keep = ("SP500", "NASDAQ", "VIX", "GLD", "SLV", "USO", "TLT")
    flags = ";".join("%s=%s" % (k, _tf[k]) for k in _tf_keep if k in _tf) or "无"
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
    # 重大财报CALL 爬虫可买序只进 #1/#2/#3 股票卡,禁止引擎区「展示条」
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
            "AMC盘后报价(Alpaca)",
            " · ".join(
                (x.get("ah_display") or "%s 盘后 %.2f(%s, %s ET)%+.1f%%vsRTH" % (
                    x.get("symbol"), x.get("mid") or 0,
                    x.get("feed_label") or "?", x.get("ah_et_hm") or "??:??",
                    x.get("vs_rth_pct") or 0,
                ))
                for x in ah_tape[:6]
            ),
        ))
    if cross.get("amc_results"):
        rows.append((
            "盘后异动(实测·Alpaca优先)",
            " · ".join(
                "%s %+.1f%%" % (x["symbol"], x["ah_chg_pct"])
                for x in cross["amc_results"][:5]
                if x.get("ah_chg_pct") is not None
            ) or "无有效 ah_chg",
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
    """HTML 对齐 Downloads/brief sample v38——禁「数据层」糊墙横幅。"""
    warn = ""
    if (cross or {}).get("liquidation_watch"):
        warn = ('<div class="banner" style="border-color:var(--red)">'
                '<b style="color:var(--red)">全线下跌 WATCH</b>'
                '<span>风险资产 %s/%s 收跌 · VIX %s%% · 商品 call 不是对冲</span></div>'
                % (_esc(cross.get("down_count")), _esc(cross.get("of")), _esc(cross.get("vix_chg_pct"))))
    # 数据层只进 footer,不进首屏(sample v38 无 Alpaca 横幅墙)
    plane_note = ""
    if hasattr(fetchers, "data_plane_banner"):
        plane_note = " · " + _short(fetchers.data_plane_banner(), 48)
    asof = (("盘初 ET %s" % fetchers.et_now_hm()) if mode == "morning" else "收盘")
    body = (warn + _engine_card(cross)
            + (_render_structured(date, data) if data else _md_fallback(raw_text)))
    return ('<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"/>'
            '<meta name="viewport" content="width=device-width,initial-scale=1"/>'
            '<title>SCOUT · %s · %s</title><style>%s</style></head><body>'
            '<header><h1>SCOUT</h1><span class="sub">%s · %s · 参谋作业,Lyra 拍板</span></header>'
            '%s<footer>build scout v3.16 · DS 决策官 JSON 结构化 · 无证据不点名 · '
            '合成 GEX 不作数 · as-of %s%s · 渲染:_render_structured/_cand_card/_md_fallback'
            '</footer></body></html>'
            % (mode.upper(), _esc(date), BRIEF_CSS, mode, _esc(date), body, asof, _esc(plane_note)))


def render_console(title, body, date, mode, data=None, cross=None, review=None):
    """DS 作业进 console 落档;晚报有 EXPANDED 时 md/html 以终稿为主、DS 原稿对照。"""
    review = review or {}
    exp = (review.get("expanded_final") or "").strip()
    meta = review.get("expanded_meta") or {}
    origin = review.get("review_origin") or review_origin_label(
        primary_label=str(review.get("primary_label") or ""),
        expanded_meta=meta,
    )
    primary = exp or body
    payload_doc = ("[DS 决策官作业·JSON(GLM review/编译直接吃)] "
                   + json.dumps(data, ensure_ascii=False)[:8000]) if data else \
                  ("[DS 决策官作业,存档] " + (body or "")[:8000])
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
    if mode == "evening" and exp:
        md = (
            "# %s\n\n"
            "## EXPANDED 终稿(b11 · EXPANDED-GLM review/编译)\n\n"
            "review_origin=%s · via=%s · substrate=%s · memory_node=%s\n\n%s\n\n"
            "---\n\n## DS 原稿(对照 · 勿当终稿)\n\n%s\n"
            % (
                title, origin, meta.get("via"), meta.get("substrate"),
                meta.get("memory_node"), exp, (body or "").strip(),
            )
        )
    elif mode == "morning" and data is not None:
        # md:有 EXPANDED 终稿则以其为主;HTML 卡片仍吃 DS structured(brief sample)
        m = (data.get("macro") or {}) if isinstance(data, dict) else {}
        ticks = [
            "#%s %s %s" % (
                c.get("rank"),
                str(c.get("ticker") or "").upper(),
                str(c.get("direction") or "call").upper(),
            )
            for c in (data.get("candidates") or [])
            if isinstance(c, dict) and c.get("ticker")
        ]
        head = (
            "# %s\n\n"
            "SP500 %s · NASDAQ %s · 置信 %s\n\n"
            "候选: %s\n\n"
            "完整格式见同目录 `%s-morning.html`(守恒渲染 · 同 brief sample)。\n"
            % (
                title,
                m.get("sp500_bias") or "—",
                m.get("nasdaq_bias") or "—",
                m.get("confidence") or "—",
                (" · ".join(ticks) if ticks else "无"),
                date,
            )
        )
        if exp:
            md = (
                "%s\n---\n\n"
                "## EXPANDED 终稿(b11 · EXPANDED-GLM review/编译)\n\n"
                "review_origin=%s · via=%s · substrate=%s · memory_node=%s\n\n%s\n"
                % (
                    head, origin, meta.get("via"), meta.get("substrate"),
                    meta.get("memory_node"), exp,
                )
            )
        else:
            md = head
    else:
        md = "# %s\n\n%s\n" % (title, body)
    with open(bp, "w", encoding="utf-8") as f:
        f.write(md)
    hp = os.path.join(bdir, "%s-%s.html" % (date, mode))
    html_src = primary if (mode == "evening" and exp) else body
    with open(hp, "w", encoding="utf-8") as f:
        f.write(render_brief_html(date, mode, data, html_src, cross))
    review_blob = {
        "primary": review.get("primary_label") or ("expanded" if exp else "ds"),
        "review_origin": origin,
        "expanded_chars": len(exp),
        "expanded_meta": meta,
        "skip_aster_integrate": SKIP_ASTER_INTEGRATE,
    }
    if data is not None:
        with open(os.path.join(bdir, "%s-%s.json" % (date, mode)), "w", encoding="utf-8") as f:
            json.dump(
                {"_engine": cross, "ds": data, "review": review_blob},
                f, ensure_ascii=False, indent=1,
            )
        if mode == "morning":
            with open(os.path.join(bdir, "%s-morning-final.md" % date), "w", encoding="utf-8") as f:
                f.write("# %s\n\n%s\n" % (title, (exp or body or "").strip()))
            if exp:
                with open(
                    os.path.join(bdir, "%s-morning-final-expanded.md" % date),
                    "w", encoding="utf-8",
                ) as f:
                    f.write("# %s · EXPANDED-GLM\n\n%s\n" % (title, exp))
    elif mode == "evening":
        with open(os.path.join(bdir, "%s-%s.json" % (date, mode)), "w", encoding="utf-8") as f:
            json.dump(
                {"_engine": cross, "review": review_blob, "ds_draft": body},
                f, ensure_ascii=False, indent=1,
            )
        with open(os.path.join(bdir, "%s-evening-final.md" % date), "w", encoding="utf-8") as f:
            f.write("# %s\n\n%s\n" % (title, primary.strip()))
        if exp:
            with open(
                os.path.join(bdir, "%s-evening-final-expanded.md" % date),
                "w", encoding="utf-8",
            ) as f:
                f.write("# %s · EXPANDED-GLM\n\n%s\n" % (title, exp))
    print(
        "[scout] 落盘:", bp, "+", hp,
        "(+json+expanded)" if exp else ("(+json)" if data is not None else ""),
    )
    return bp


def emit_aether_scout(
    date, mode, title, body, bp, *,
    data=None, cross=None, ds_draft="", expanded_final="", expanded_meta=None,
    primary_label="",
):
    """本机接线:落盘后 emit → 8501 store → aether OPTION(装包原版无此步,部署必接)。"""
    meta = expanded_meta or {}
    # body 禁塞 DS 原始 JSON(OPTION 曾当早报喷墙);structured 保留全量,ds_draft 留原稿
    body_for_store = body
    raw = (body or "").strip()
    if data is not None and (raw.startswith("{") or raw.startswith("[")):
        m = data.get("macro") if isinstance(data, dict) else {}
        m = m if isinstance(m, dict) else {}
        ticks = [
            str(c.get("ticker") or "").upper()
            for c in ((data.get("candidates") or []) if isinstance(data, dict) else [])
            if isinstance(c, dict) and c.get("ticker")
        ]
        body_for_store = (
            "SP500 %s · NASDAQ %s · 置信 %s · 候选 %s · 读 briefs/%s-%s.html"
            % (
                m.get("sp500_bias") or "—",
                m.get("nasdaq_bias") or "—",
                m.get("confidence") or "—",
                (",".join(ticks) or "无"),
                date, mode,
            )
        )
        # 晨会 JSON 只落 briefs/*.json；store body/ds_draft 一律不带原始 JSON
        ds_draft = ""
    payload = {
        "date": date, "mode": mode, "title": title, "body": body_for_store,
        "brief_path": bp,
        "via": "scout_v3_16_5_expanded_glm" if expanded_final else "scout_v3_15_local",
        "ds_draft": ds_draft or "",
        "expanded_final": expanded_final or "",
        "expanded_meta": meta,
        "primary_review": primary_label or ("expanded" if expanded_final else "ds"),
        "review_origin": review_origin_label(
            primary_label=primary_label or ("expanded" if expanded_final else "ds"),
            expanded_meta=meta,
        ),
        "skip_aster_integrate": SKIP_ASTER_INTEGRATE,
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
    ap.add_argument(
        "--review",
        choices=["expanded", "none", "ds"],
        default=os.getenv("SCOUT_REVIEW", DEFAULT_REVIEW),
        help="晨会+晚报 review/编译:默认 expanded(=EXPANDED-GLM);none/ds=仅 DS",
    )
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
        clock = morning_clock()
        cross["morning_clock"] = clock
        load_equity_universe()  # 响亮打印层A规模
        cross["earnings_movers"] = earnings_movers(payload, today)
        cross["amc_tonight"] = amc_tonight(payload, today)
        cross["major_earnings"] = major_earnings_calls(payload, today)
        cross["live_leaders"] = live_universe_leaders(
            cross, top_n=12, et_hm=clock["et_hm"], phase=clock["phase"],
        )
        t0_pool = _t0_earnings_pool(cross, phase=clock["phase"])
        cross["t0_pool"] = t0_pool
        print("[scout] morning_clock", clock["et_hm"], clock["phase"])
        print("[scout] live_leaders→硬锁#1/#2/#3(今开后)", [
            "%s/intra%+.2f%%/gap%s/day%+.1f%%" % (
                m["symbol"], m.get("intra_pct") or 0,
                (("/%+.1f%%" % m["gap_pct"]) if m.get("gap_pct") is not None else ""),
                m.get("chg_pct") or 0,
            )
            for m in (cross.get("live_leaders") or [])[:6]
        ])
        print("[scout] major_earnings(对照·已出完不占席)", [
            "%s/%s" % (m["symbol"], m["when"])
            for m in (cross.get("major_earnings") or [])[:8]
        ])
        print("[scout] t0_pool head", t0_pool[:16])
        print("[scout] earnings_movers(全市场对照)", [
            "%s%s%+.1f%%" % (
                (m.get("symbol") if isinstance(m, dict) else m),
                ("/" + m["when"]) if isinstance(m, dict) and m.get("when") else "",
                (m.get("chg_pct") or 0) if isinstance(m, dict) else 0,
            )
            for m in (cross.get("earnings_movers") or [])[:8]
        ])
        evening_ammo = load_evening_ammo(today)
        if evening_ammo:
            print("[scout] evening_ammo chars", len(evening_ammo))
        prev = load_prev_review(today)
        if prev:
            prev["rolling"] = rolling_summary(prev["date"])
            cross["prev_review"] = {"date": prev["date"], "hit": prev["hit"], "rolling": prev["rolling"]}
        ws = fetch_workstation_state()
        body = ds_call(build_trading_prompt(
            payload, ws, yday, cross, prev, evening_ammo=evening_ammo,
        ))
        data = _extract_json(body)
        if data is None:
            print("[scout] DS 未按 JSON schema 输出——晨会单降级为文本分节渲染(响亮记录)")
        else:
            data = apply_liquidity_gate(data)
            data = force_candidates_call_only(data)
            data = ensure_candidates(data, cross, phase=clock["phase"])
            data["candidates"] = _assign_ranks(
                data.get("candidates") or [],
                pool=t0_pool,
            )
            # 再 ensure 一次:剔 PUT / pool 过滤后若不足 3 张继续补 CALL
            if len(data.get("candidates") or []) < CANDIDATE_RANK_N:
                data = ensure_candidates(data, cross, phase=clock["phase"])
                data["candidates"] = _assign_ranks(
                    data.get("candidates") or [],
                    pool=t0_pool,
                )
            # 排名理由硬闸:缺则占位(UI 主区必显)
            for c in data.get("candidates") or []:
                if isinstance(c, dict) and not str(c.get("rank_reason") or "").strip():
                    c["rank_reason"] = "【待补排名理由】#%s" % c.get("rank")
            print("[scout] ranks", [
                "#%s %s" % (c.get("rank"), c.get("ticker"))
                for c in (data.get("candidates") or [])
            ])
            if len(data.get("candidates") or []) != CANDIDATE_RANK_N:
                print("[scout] WARN 铁律违例: candidates=%d (须=%d)"
                      % (len(data.get("candidates") or []), CANDIDATE_RANK_N))
        print("[scout] amc_tonight", [
            ("%s%+.1f%%" % (x.get("symbol"), x["chg_pct"])) if isinstance(x, dict) and x.get("chg_pct") is not None
            else (x.get("symbol") if isinstance(x, dict) else x)
            for x in (cross.get("amc_tonight") or [])[:12]
        ])
        print("[scout] rsi14_tape", cross.get("rsi14_tape"))
        title = "Scout 晨会交易任务单 · " + today
        expanded_final = ""
        expanded_meta = {}
        primary = body
        primary_label = "ds"
        if a.review == "expanded":
            print(
                "[scout] 晨会 EXPANDED-GLM review · skip_aster=%s · memory=%s · wb=%s"
                % (SKIP_ASTER_INTEGRATE, scout_expanded_memory_node(today), WB)
            )
            er = expanded_morning_review(
                body, data, cross=cross, today=today,
            )
            expanded_final = (er.get("text") or "").strip()
            expanded_meta = er.get("meta") or {}
            print("[scout] EXPANDED meta(morning)", {
                k: expanded_meta.get(k)
                for k in ("review_origin", "substrate", "via", "memory_node",
                          "cloud_backend", "error")
            })
            if expanded_final and expanded_meta.get("via") != "fallback_ds":
                primary = expanded_final
                primary_label = "expanded"
        bp = render_console(
            title, body, today, "morning", data, cross,
            review={
                "expanded_final": (
                    expanded_final if primary_label == "expanded" else ""
                ),
                "expanded_meta": expanded_meta,
                "primary_label": primary_label,
                "review_origin": review_origin_label(
                    primary_label=primary_label, expanded_meta=expanded_meta
                ),
            },
        )
        emit_aether_scout(
            today, "morning", title, primary, bp,
            data=data, cross=cross, ds_draft=body,
            expanded_final=(
                expanded_final if primary_label == "expanded" else ""
            ),
            expanded_meta=expanded_meta, primary_label=primary_label,
        )
    else:
        # v3.13(守恒):晚班也算异动榜(全日K线,反而更准)——雷达要求点名的读数必须存在
        cross["earnings_movers"] = earnings_movers(payload, today)
        cross["amc_tonight"] = amc_tonight(payload, today)
        cross["amc_session_tape"] = amc_session_tape(cross["amc_tonight"])
        cross["amc_ah_tape"] = amc_ah_tape(cross["amc_tonight"])
        # patch 盘后漏洞:amc_results = 实测盘后涨跌;|AH|≥8% 必须进雷达(DOCS +68% 判例)
        # Nasdaq secondary 常空 → 用 Alpaca amc_ah_tape 同源数字填 ah_chg_pct(ETF 仍 Alpaca)
        amc_syms = _amc_sym_list(cross.get("amc_tonight") or [])
        by = {}
        if amc_syms and hasattr(fetchers, "fetch_afterhours"):
            ah = fetchers.fetch_afterhours(amc_syms[:80])
            for i in (ah.get("items") or []):
                if i.get("ah_chg_pct") is not None:
                    by[i["symbol"]] = i
        for x in (cross.get("amc_ah_tape") or []):
            sym = (x.get("symbol") or "").upper()
            pct = x.get("vs_rth_pct")
            if sym and pct is not None and sym not in by:
                by[sym] = {
                    "symbol": sym, "close": x.get("rth_close"), "ah_last": x.get("mid"),
                    "ah_chg_pct": pct, "source": x.get("source") or "alpaca",
                    "ah_display": x.get("ah_display"),
                }
        cross["amc_results"] = sorted(by.values(), key=lambda r: -abs(r.get("ah_chg_pct") or 0))
        print("[scout] amc_tonight", [
            ("%s%+.1f%%" % (x.get("symbol"), x["chg_pct"])) if isinstance(x, dict) and x.get("chg_pct") is not None
            else (x.get("symbol") if isinstance(x, dict) else x)
            for x in (cross.get("amc_tonight") or [])[:12]
        ], "n=%d DOCS=%s" % (
            len(cross.get("amc_tonight") or []),
            "Y" if any(_amc_row_sym(x) == "DOCS" for x in (cross.get("amc_tonight") or [])) else "N",
        ))
        print("[scout] amc_session_tape", [
            "%s%+.1f%%" % (x["symbol"], x["chg_pct"])
            for x in (cross.get("amc_session_tape") or [])[:8]
        ])
        print("[scout] amc_ah_tape", [
            x.get("ah_display") or "%s AH%+.1f%%" % (x["symbol"], x.get("vs_rth_pct") or 0)
            for x in (cross.get("amc_ah_tape") or [])[:8]
        ])
        print("[scout] amc_results", [
            "%s%+.1f%%" % (x["symbol"], x["ah_chg_pct"])
            for x in (cross.get("amc_results") or [])[:8]
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
        inv = source_inventory(payload)
        yday_inv = source_inventory(yday) if yday else None
        title = "Scout 晚报复盘 · " + today
        body = evening_ds_with_lint(
            build_evening_prompt(payload, yday, cross, rev), inv, yday_inv
        )
        expanded_final = ""
        expanded_meta = {}
        primary = body
        primary_label = "ds"
        if a.review == "expanded":
            print(
                "[scout] 晚报 EXPANDED-GLM review · skip_aster=%s · memory=%s · wb=%s"
                % (SKIP_ASTER_INTEGRATE, scout_expanded_memory_node(today), WB)
            )
            er = expanded_evening_review(
                body, inv=inv, yday_inv=yday_inv, today=today
            )
            expanded_final = (er.get("text") or "").strip()
            expanded_meta = er.get("meta") or {}
            print("[scout] EXPANDED meta(evening)", {
                k: expanded_meta.get(k)
                for k in ("review_origin", "substrate", "via", "memory_node",
                          "cloud_backend", "error")
            })
            if expanded_final and expanded_meta.get("via") != "fallback_ds":
                primary = expanded_final
                primary_label = "expanded"
            else:
                primary = body
                primary_label = "ds"
        bp = render_console(
            title, body, today, "evening", None, cross,
            review={
                "expanded_final": (
                    expanded_final if primary_label == "expanded" else ""
                ),
                "expanded_meta": expanded_meta,
                "primary_label": primary_label,
                "review_origin": review_origin_label(
                    primary_label=primary_label, expanded_meta=expanded_meta
                ),
            },
        )
        emit_aether_scout(
            today, "evening", title, primary, bp,
            data=None, cross=cross, ds_draft=body,
            expanded_final=(
                expanded_final if primary_label == "expanded" else ""
            ),
            expanded_meta=expanded_meta, primary_label=primary_label,
        )


if __name__ == "__main__":
    main()
