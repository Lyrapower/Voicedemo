#!/usr/bin/env python3
"""scout_agent.py —— Scout Agent v3.7(守恒交付 + 本机累加 patch)

版本纪律:v3.3→…→v3.6→v3.7 是累加 patch,不是整版替代(禁跑 install 整包覆盖本机接线)。
v3.7(Lyra 反转):晨班 6:45 PST=开盘后15分钟盘初 tape;prompt 强制部分K线口径;
  晚报 21:00 完整日线,挤兑判据在晚报最硬。
BRIEF_CSS/_render_* 零改动权见 UI WIRING。
本机累加:
  · .env · Ollama deepseek-v4-pro · 默认 SCOUT_REVIEW=expanded(驳回 Aster);早晚班同链
  · 默认复用今日 raw(SCOUT_SKIP_FETCH=1);重采显式 --fetch;全采 0 ok 自动回退好 raw
  · v3.4 ensure_hedge 硬闸保留;briefs 重跑先归档再写(禁抹掉前日/前次)
  · ensure_candidates:主菜=个股卡铁律——恰 3 张、rank 1/2/3、rank_reason、仅 SP500∪Nasdaq100
  · 对冲腿(贵金属/原油/海外ADR等)不进个股宇宙池——ensure_hedge 不做宇宙过滤
  · Lyra 否决票:SCOUT_BAN_TICKERS(默认含 EA)——否决标的不算主菜,硬闸剔除并补位
  · 对冲三灯(引擎):指数冲高回落 + 恐贪极值 + GLD 强势 → distribution_hint 抬风险地板
  · console/aether emit 沿用既有路径
"""
from __future__ import annotations
import argparse, datetime, html, json, os, re, sys, urllib.error, urllib.request
from pathlib import Path

import fetchers

_HERE = Path(__file__).resolve().parent

# Lyra 否决:不算主菜(可环境变量追加,逗号分隔)
_BAN = {"EA"}
_BAN |= {t.strip().upper() for t in os.getenv("SCOUT_BAN_TICKERS", "").split(",") if t.strip()}

_UNIVERSE_CACHE: set[str] | None = None
CANDIDATE_RANK_N = 3


def load_equity_universe() -> set[str]:
    """个股候选宇宙 = SP500 ∪ Nasdaq-100。对冲标的不进此池。"""
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
    # 显式排除常见对冲/指数壳——即使误入名单也不得当主菜个股
    uni -= {
        "SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "USO", "UNG", "TLT", "UUP",
        "VIXY", "UVXY", "FXI", "KWEB", "EWZ", "EWJ", "EEM", "YINN", "YANG",
    }
    _UNIVERSE_CACHE = uni
    print("[scout] 个股宇宙加载 %d 只(SP500∪NDX;对冲腿不校验)" % len(uni))
    return uni


def in_equity_universe(ticker: str) -> bool:
    t = str(ticker or "").strip().upper().replace(".", "-")
    return bool(t) and t in load_equity_universe()


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_dotenv(_HERE / ".env")

DS_BASE = os.getenv("DEEPSEEK_BASE", "http://127.0.0.1:11434/v1").rstrip("/")
DS_KEY = os.getenv("DEEPSEEK_API_KEY", "ollama").strip()
DS_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro:cloud")
GW = os.getenv("GATEWAY_URL", "http://127.0.0.1:8501").rstrip("/")
WB = os.getenv("WORKBENCH_URL", "http://127.0.0.1:8515").rstrip("/")
GLM_MODEL = os.getenv("GLM_MODEL", "glm-5.2:cloud")
CONSOLE = os.getenv("CONSOLE_URL", "http://localhost:8610").rstrip("/")
CONSOLE_KEY = os.getenv("CONSOLE_KEY", "").strip()
OWS = os.getenv("OWS_URL", "http://localhost:8620").rstrip("/")
OUT = os.getenv("SCOUT_OUT", str(_HERE))
EXPANDED_MEMORY_NODE = os.getenv("SCOUT_EXPANDED_MEMORY_NODE", "scout-review").strip() or "scout-review"
DEFAULT_REVIEW = "expanded"
SKIP_ASTER_INTEGRATE = os.getenv("SCOUT_SKIP_ASTER", "1").strip() not in ("0", "false", "no")


def _ds_via_ollama() -> bool:
    return "11434" in DS_BASE or (
        DS_BASE.endswith("/v1") and "deepseek.com" not in DS_BASE
    )



def _http(url, body=None, headers=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ---- workstation 数据联动 ----
def fetch_workstation_state():
    """取 8620 最新非 synthetic 日;全是合成则拒喂 DS(不作数)。"""
    try:
        dates = _http(OWS + "/api/dates", timeout=5)
        if not dates:
            return None
        # 从新到旧找实弹 source
        for day in reversed(dates):
            try:
                d = _http(OWS + "/api/day/" + day, timeout=8)
            except Exception:
                continue
            src = str((d.get("snap") or {}).get("source") or "")
            if src.startswith("synthetic"):
                continue
            ws = {"date": day, "underlying": d["snap"]["underlying"],
                  "spot": d["snap"]["spot"], "net_gex": d["gex"]["net_gex_musd_per_1pct"],
                  "gamma_flip": d["gex"]["gamma_flip"], "ivp": d["features"]["ivp"],
                  "vrp": d["features"]["vrp20"], "source": src,
                  "atm_iv30": (d.get("features") or {}).get("atm_iv30")}
            print("[scout] workstation 实弹 %s source=%s gex=%s ivp=%s"
                  % (day, src, ws.get("net_gex"), ws.get("ivp")))
            return ws
        print("[scout] workstation 仅合成演示数据——不作数,不喂 DS")
        return None
    except Exception as e:
        print("[scout] workstation(:8620) 不可达:", e)
        return None


def engine_data_gaps(payload, yday, ws) -> list:
    """第四节缺口由引擎据实填——禁止 DS 凭感觉编「SSL 全挂」等假缺口。"""
    gaps = []
    results = (payload or {}).get("results") or []
    by_src = {r.get("source"): r for r in results if isinstance(r, dict)}

    fred = by_src.get("fred_macro") or {}
    if not fred.get("ok"):
        gaps.append({
            "item": "FRED宏观数据",
            "status": "不可用(%s)" % ((fred.get("error") or "未采集")[:120]),
            "handling": "已尝试 FRED key / BLS+NYFed 回退仍失败时,宏观改看收益率曲线与 Polymarket",
        })
    # fred ok(含 BLS/NYFed 回退)=已解决,不进缺口清单;via 留在 raw items 供引用

    y_ok = 0
    if isinstance(yday, dict):
        y_ok = sum(1 for r in (yday.get("results") or []) if r.get("ok"))
    if not yday:
        gaps.append({
            "item": "昨日完整日线数据",
            "status": "无昨日 raw 落盘",
            "handling": "无法对比昨收形态;仅用今日盘初/隔夜截面",
        })
    elif y_ok <= 0:
        gaps.append({
            "item": "昨日完整日线数据",
            "status": "昨日 raw 存在但 0 源成功",
            "handling": "检查 raw 选优(_pick_day_raw);勿把 SSL 失败戳记稿当全日失败",
        })

    if not ws:
        gaps.append({
            "item": "工作站GEX/特征数据",
            "status": "无实弹(仅 synthetic 或 8620 不可达)",
            "handling": "关键位改用盘初高低/昨收;跑 alpaca_loader/theta_loader 灌 OWS raw 后重拉",
        })
    return gaps


def ensure_data_gaps(data, engine_gaps: list):
    """引擎缺口覆盖同名 item;保留 DS 额外矛盾标注(不同名)。"""
    if not isinstance(data, dict):
        return data
    eng = [g for g in (engine_gaps or []) if isinstance(g, dict) and g.get("item")]
    ds = [g for g in (data.get("data_gaps") or []) if isinstance(g, dict) and g.get("item")]
    eng_items = {g["item"] for g in eng}
    # 假缺口黑名单:引擎已证明昨日有好 raw 时,DS 不得再写 SSL 全挂
    merged = list(eng)
    for g in ds:
        item = str(g.get("item") or "")
        if item in eng_items:
            continue
        st = str(g.get("status") or "")
        # 引擎已证明昨日有好 raw → 丢弃 DS「SSL 全挂」假缺口
        if "昨日" in item and ("SSL" in st or "ssl" in st) and not any(
            "昨日" in e.get("item", "") for e in eng
        ):
            print("[scout] 丢弃 DS 假缺口:", item, st[:60])
            continue
        # 引擎清单空且工作站已实弹 → 丢弃 DS 再编的 GEX/IV 缺失
        if not eng and any(k in item for k in ("工作站", "GEX", "IV", "ivp", "隐含波动")):
            if "缺失" in st or "null" in st.lower() or "不可用" in st:
                print("[scout] 丢弃 DS 假缺口(实弹已到):", item, st[:60])
                continue
        merged.append(g)
    data["data_gaps"] = merged
    return data


def yesterday_raw(today):
    """上一交易日对比 raw——按「ok 源数」选,禁止 mtime 最新的 SSL 全挂稿盖掉好日线。

    事故(2026-08-06):16:48 全采 0/9(SSL) 写成 2026-08-05-1648.json,
    旧逻辑按 mtime 取它 → DS 误报「昨日完整日线全部 SSL 失败」,
    实际 canonical 2026-08-05.json 已是 8/9 好稿。
    """
    try:
        rawdir = os.path.join(OUT, "raw")
        days = {f[:10] for f in os.listdir(rawdir)
                if f.endswith(".json") and len(f) >= 10 and f[:10] < today}
        if not days:
            return None
        last_day = max(days)
        pick = _pick_day_raw(rawdir, last_day)
        if not pick:
            return None
        n = _raw_ok_count(pick)
        print("[scout] 昨日对比 raw(%d ok) → %s" % (n, pick))
        if n <= 0:
            print("[scout] 【响亮】昨日 raw 无可用源——对比弹药空(非默认真全日失败)")
        return json.load(open(pick, encoding="utf-8"))
    except Exception as e:
        print("[scout] yesterday_raw 失败:", e)
        return None


# ---- DS 决策官 prompt(v3.2 池化 + v3.7 盘初口径) ----
def build_trading_prompt(raw, ws, yday, cross=None, engine_gaps=None):
    ammo = _hedge_ammo(raw)
    ammo_line = json.dumps(ammo, ensure_ascii=False)[:3500]
    gaps_line = json.dumps(engine_gaps or [], ensure_ascii=False)[:2000]
    return f"""你是交易台的首席决策官。现在是开盘后约 15 分钟(9:45 ET),
基于隔夜数据 + 盘初 tape 给出清晰的分析作业
(这是给交易员参考的分析,交易员自己拍板执行,不是自动下单)。
观察宇宙 = S&P 500 与 Nasdaq 成分池(不是 SPY/QQQ 两只 ETF)。
读数口径铁律(不标注会把部分K线冒充全日判断——禁止):
- indices/hedge_assets 的当日行是盘初部分K线(开盘~15分钟,非收盘完整日线)
- chg_pct 是盘初对昨收,不是全日涨跌
- tape_flag/close_loc 按盘初形态解读,不当全日形态用
- 15 分钟的「冲高回落」与收盘的「冲高回落」不是同一证据等级;写 logic/basis 时必须标明「盘初」
- 昨日完整日线形态看晚报与昨日采集;全线下跌/挤兑硬判据以晚报完整日线为准,晨会只作盘初预警

隔夜采集:{json.dumps(raw, ensure_ascii=False)[:6000]}
工作站读数(GEX/特征):{json.dumps(ws, ensure_ascii=False) if ws else "工作站无可用实弹数据(不可达或仅合成数据),基于隔夜数据判断"}
昨日采集(对比用):{json.dumps(yday, ensure_ascii=False)[:2000] if yday else "无"}
跨资产引擎读数(确定性,判断必须引用;晨班=盘初截面):{json.dumps(cross, ensure_ascii=False) if cross else "无"}
对冲弹药(引擎实测,hedge 必须引用数字;GLD/SLV 等勿漏读):{ammo_line}
出货三灯/风险地板(引擎,必须引用;齐亮时 DS 不得压成低):
{json.dumps({k: (cross or {}).get(k) for k in ("distribution_lights","distribution_hint","distribution_basis")}, ensure_ascii=False)}
数据缺口引擎清单(第四节 data_gaps 必须以本清单为准;禁止编造 SSL 全挂等未列出的假缺口;可追加清单外的真矛盾):
{gaps_line}

交易风格偏置(硬约束):交易员主做 T+0 单腿 CALL,当日了结。
- 策略默认形态 = 单腿 CALL,到期选 0DTE 或最近可用到期,必须给 t0_exit(当日平仓纪律)
- PUT 仅当看空证据明确时才提,并在 evidence 写清依据;禁止多腿组合;禁止编造权利金/报价
候选铁律(主菜=个股卡·Lyra 硬铁律——空清单非法):
- 必须恰好输出 3 张个股观察卡,rank 字段分别为 1、2、3(禁止并列、禁止缺号)
- 每卡必须写 rank_reason:相对其他候选为何排此名次(催化强度/证据新鲜度/盘初可交易性/风险)
- 个股 ticker 必须 ∈ S&P500 ∪ Nasdaq-100 成分池;SPY/QQQ 只做大盘环境,禁止当主菜
- 宇宙池只约束 candidates——对冲腿(GLD/SLV/OXY/USO/海外 ADR 等)不进此池、不做成分校验
- 否决票(不算主菜,禁止出现在 candidates):{sorted(_BAN)}
- 每卡必须锚定隔夜采集具体条目(EDGAR/FDA/赔率/指数与宏观读数),逐条给出处
- 优先提名「filed=今日」的 EDGAR;仅有「8-K 提交事实、无正文摘要」仍可作弱证据落卡,
  但 evidence.why 必须写明「仅提交事实·无正文·弱催化」,abandon 写清开盘未确认则作废
- 禁止凭训练记忆点名未出现在采集里的 ticker;禁止编造权利金
- 若 EDGAR 多为池外微盘:仍必须从 SP500∪Nasdaq100 提名 3 张,证据改锚 indices/macro/赔率实读,
  不得用 LEG 等池外代码凑数;rank_reason 写清相对排序
- no_candidate_reason 仅当采集源全空时才许非空;有读数却交白卷/只点池外=违铁律
对冲铁律(hedge 段永不空白——"没信号什么都不写"被禁止):
- 对冲范围=贵金属/原油/汇率国债/波动率/海外 ADR 等工具池——不受 S&P500∪Nasdaq 个股宇宙限制
- 用跨资产引擎读数 + fear_greed + hedge_assets 评估风险;distribution_risk 不得低于
  引擎 distribution_hint(三灯齐亮=高;亮2/3或指数冲高回落+贪婪=中)
- 先定 regime,写进 distribution_risk + basis(必须引用 chg_pct/close_loc/tape_flag/恐贪数字)
- 风险 中/高 → 必须按下表给 1-2 条对冲腿(GLD/SLV/OXY/USO 池优先,单腿 call、T+0、禁编报价)
- 风险 低 → note 写明为何暂不需对冲(不许留空);池内无个股候选不是 hedge 空白的理由
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
 "candidates": [{{"rank": 1, "ticker": "", "direction": "call|put",
   "rank_reason": "为何排第1(相对#2/#3的优先依据)",
   "evidence": [{{"source": "edgar|fda|polymarket|indices|macro", "item": "条目摘要", "why": "为何构成驱动"}}],
   "key_levels": "该标的阻力/支撑及依据",
   "strategy": {{"type": "单腿 call", "strike_logic": "行权价选择逻辑(不编报价)",
     "expiry": "0DTE|本周五|最近到期", "entry_condition": "入场触发条件",
     "stop": "止损条件", "abandon": "作废条件", "t0_exit": "当日平仓纪律"}}}},
  {{"rank": 2, "ticker": "", "direction": "call|put", "rank_reason": "为何排第2",
   "evidence": [{{"source": "edgar|fda|polymarket|indices|macro", "item": "", "why": ""}}],
   "key_levels": "", "strategy": {{"type": "单腿 call", "strike_logic": "", "expiry": "0DTE",
     "entry_condition": "", "stop": "", "abandon": "", "t0_exit": ""}}}},
  {{"rank": 3, "ticker": "", "direction": "call|put", "rank_reason": "为何排第3",
   "evidence": [{{"source": "edgar|fda|polymarket|indices|macro", "item": "", "why": ""}}],
   "key_levels": "", "strategy": {{"type": "单腿 call", "strike_logic": "", "expiry": "0DTE",
     "entry_condition": "", "stop": "", "abandon": "", "t0_exit": ""}}}}],
 "no_candidate_reason": "仅当采集源全空无法提名时填写;有条目却凑不齐3张池内卡时写明缺口,否则空串",
 "hedge": {{"distribution_risk": "高|中|低", "regime": "轮动|资金迁徙(海外)|全线下跌|无明显风险",
   "basis": "引用跨资产引擎/fear_greed/hedge_assets 读数的依据",
   "legs": [{{"ticker": "GLD|SLV|OXY|USO|TLT|UUP|VIXY|SPY|QQQ|FXI|KWEB|EWZ|EWJ|EEM|BABA|YINN", "direction": "call|put",
     "evidence": [{{"source": "hedge_assets|fear_greed|indices|macro", "item": "读数", "why": "为何对冲"}}],
     "strategy": {{"type": "单腿 call", "strike_logic": "", "expiry": "0DTE|本周五|最近到期",
       "entry_condition": "", "stop": "", "abandon": "", "t0_exit": ""}}}}],
   "note": "风险低暂不对冲时写明依据;永不空白;对冲腿不受个股宇宙限制"}},
 "data_gaps": [{{"item": "", "status": "", "handling": ""}}],
 "conclusion": "一句话结论"}}
data_gaps 铁律:必须覆盖引擎缺口清单;禁止把「昨日有好 raw」写成 SSL 全失败;工作站仅 synthetic 时如实写无实弹。
禁止"具体视情况而定""谨慎操作"等无效废话。全部值用中文。"""


def build_evening_prompt(raw, yday, cross=None):
    return f"""你是交易台参谋。现在是收盘后(21:00 本机班次),写今日完整日线复盘 + 明日弹药,给交易员看。
读数口径:本班 indices/hedge_assets 是完整日线(非盘初部分K线);
tape_flag/close_loc/chg_pct 按全日形态解读;liquidation_watch 等挤兑判据在本班最硬
(晨会 6:45 盘初「冲高回落」证据等级低于本班收盘形态——勿把晨会预警直接升格为全日铁证)。
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
跨资产引擎读数(完整日线截面):{json.dumps(cross, ensure_ascii=False) if cross else "无"}
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
    url = DS_BASE + ("/chat/completions" if DS_BASE.endswith("/v1") or "deepseek.com" in DS_BASE
                     else "/v1/chat/completions")
    if DS_BASE.endswith("/v1"):
        url = DS_BASE + "/chat/completions"
    body = {
        "model": DS_MODEL,
        "max_tokens": int(os.getenv("DEEPSEEK_MAX_TOKENS", "8000")),
        "messages": [{"role": "user", "content": prompt}],
    }
    if _ds_via_ollama():
        body["think"] = False
    r = _http(url, body, {"Authorization": "Bearer " + DS_KEY}, timeout=300)
    msg = (r.get("choices") or [{}])[0].get("message") or {}
    text = (msg.get("content") or "").strip()
    if not text:
        raise SystemExit("[scout] DS 空正文 model=%s" % DS_MODEL)
    return text


def cross_asset_summary(payload):
    """确定性跨资产读数(数字出引擎,解读归 DS)。
    全线下跌体制判据:6 只风险资产(SP500/NASDAQ/GLD/SLV/OXY/USO)≥5 收跌
    且 VIX 单日 ≥ +8%——此时黄金原油同跌,商品 call 不构成对冲。
    累加 patch:raw 落盘键是 results(非 sources)——读错则引擎永远空、GLD 进不了芯片。"""
    m = {}
    rows = payload.get("results") or payload.get("sources") or []
    for src in rows:
        if src.get("source") in ("indices", "hedge_assets") and src.get("ok") is not False:
            for it in src.get("items") or []:
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
    # 拉高出货三灯(数字出引擎):指数冲高回落 + 恐贪极值 + GLD 强势收高
    # ——齐亮时 DS 不得把 distribution_risk 压成「低」
    out.update(_distribution_lights(payload, out))
    return out


def _distribution_lights(payload, cross=None):
    """确定性出货风险地板。返回 distribution_lights / distribution_hint / distribution_basis。"""
    ammo = _hedge_ammo(payload if isinstance(payload, dict) else {"results": []})
    idx = ammo.get("indices_tape") or []
    spx_dist = any(
        t.get("name") in ("SP500", "NASDAQ") and t.get("tape_flag") == "冲高回落"
        for t in idx
    )
    fg = (ammo.get("fear_greed") or [{}])[0] if ammo.get("fear_greed") else {}
    try:
        fg_score = float(fg.get("score") or 0)
    except (TypeError, ValueError):
        fg_score = 0.0
    fg_rating = str(fg.get("rating") or "").lower()
    # 极贪:CNN extreme greed 或 score≥75;「贪婪」单独不够亮第三灯
    fg_extreme = fg_score >= 75.0 or "extreme" in fg_rating
    hedges = ammo.get("hedge_assets") or []
    gld = next((a for a in hedges if (a.get("name") or a.get("ticker")) == "GLD"), None) or {}
    gld_strong = (
        gld.get("tape_flag") == "强势收高"
        or ((gld.get("chg_pct") or 0) > 0 and (gld.get("close_loc") or 0) >= 0.8)
    )
    lights = {
        "index_distribution": spx_dist,   # SP500/NASDAQ tape_flag=冲高回落
        "fear_greed_extreme": fg_extreme, # 恐贪极值
        "gld_bid": gld_strong,            # GLD 强势收高/买盘
        "fear_greed_score": fg_score,
        "fear_greed_rating": fg.get("rating"),
        "gld_chg_pct": gld.get("chg_pct"),
        "gld_tape": gld.get("tape_flag"),
    }
    n = sum(1 for k in ("index_distribution", "fear_greed_extreme", "gld_bid") if lights[k])
    if n >= 3:
        hint, basis = "高", "三灯齐亮:指数冲高回落+恐贪极值+GLD强势——拉高出货语境"
    elif n == 2:
        hint, basis = "中", "出货三灯亮2/3——中度拉高出货预警(引擎地板)"
    elif spx_dist and (fg_score >= 55 or "greed" in fg_rating):
        # 指数出货形 + 贪婪(非极)也抬到中,避免 DS 一句感觉压成低
        hint, basis = "中", "指数冲高回落且恐贪偏贪——中度预警(引擎地板)"
        lights["soft_greed_floor"] = True
    else:
        hint, basis = "低", "出货三灯未齐(引擎);低风险须写清 note 依据"
    return {
        "distribution_lights": lights,
        "distribution_hint": hint,
        "distribution_basis": basis,
    }


def _hedge_ammo(raw):
    """v3.4 累加:从 raw.results 抽出对冲判断弹药(引擎实测),单独喂 DS 防漏读。"""
    ammo = {"indices_tape": [], "hedge_assets": [], "fear_greed": [], "polymarket_event": []}
    for r in (raw or {}).get("results") or []:
        src, items = r.get("source"), r.get("items") or []
        if not r.get("ok"):
            continue
        if src == "indices":
            for it in items:
                ammo["indices_tape"].append({
                    "name": it.get("name"),
                    "close": it.get("close") or it.get("Close"),
                    "chg_pct": it.get("chg_pct"),
                    "close_loc": it.get("close_loc"),
                    "tape_flag": it.get("tape_flag"),
                    "source": it.get("source"),
                    "proxy": it.get("proxy"),
                })
        elif src == "hedge_assets":
            ammo["hedge_assets"] = [
                {"ticker": it.get("ticker") or it.get("name"), "name": it.get("name"),
                 "close": it.get("close") or it.get("Close"),
                 "chg_pct": it.get("chg_pct"), "close_loc": it.get("close_loc"),
                 "tape_flag": it.get("tape_flag"), "source": it.get("source")}
                for it in items
            ]
        elif src == "fear_greed":
            ammo["fear_greed"] = items
        elif src == "polymarket_odds":
            ammo["polymarket_event"] = [it for it in items if it.get("bucket") == "event"][:20]
    return ammo


def _engine_hedge_legs(raw, limit=2):
    """v3.4 累加:风险中/高且 DS 漏腿时用引擎实测补 1-2 条(禁编报价)。"""
    ammo = _hedge_ammo(raw if isinstance(raw, dict) else {"results": raw or []})
    picks = []
    assets = list(ammo.get("hedge_assets") or [])
    assets.sort(
        key=lambda a: (
            0 if (a.get("name") in ("GLD", "SLV") and (a.get("chg_pct") or 0) > 0) else 1,
            -(abs(a.get("chg_pct") or 0)),
        )
    )
    idx_dist = any(
        (t.get("tape_flag") == "冲高回落" and t.get("name") in ("SP500", "NASDAQ"))
        for t in (ammo.get("indices_tape") or [])
    )
    for a in assets:
        if len(picks) >= limit:
            break
        name = a.get("name") or a.get("ticker")
        if name not in ("GLD", "SLV", "OXY", "USO"):
            continue
        chg = a.get("chg_pct")
        cl = a.get("close_loc")
        flag = a.get("tape_flag") or ""
        why = "引擎补位: %s chg_pct=%s close_loc=%s tape=%s" % (name, chg, cl, flag or "—")
        if idx_dist:
            why += "; 大盘 tape_flag=冲高回落"
        picks.append({
            "ticker": name,
            "direction": "call",
            "evidence": [{
                "source": "hedge_assets",
                "item": "%s chg_pct=%s close_loc=%s" % (name, chg, cl),
                "why": why,
            }],
            "strategy": {
                "type": "单腿 call",
                "strike_logic": "ATM 上一档(禁编报价,以盘口为准)",
                "expiry": "本周五",
                "entry_condition": "高开不回补或盘中确认避险延续",
                "stop": "权利金 -30%",
                "abandon": "大盘收复日高且对冲腿转弱",
                "t0_exit": "15:30 ET 前了结",
            },
        })
    return picks


def _ticker_from_edgar_company(company: str) -> str | None:
    """'Foo Inc.  (SUNS)  (CIK …)' → SUNS;过滤过短/明显非 ticker。"""
    if not company:
        return None
    found = re.findall(r"\(([A-Z]{1,5})\)", company)
    for t in found:
        if t in ("CIK", "LLC", "INC", "CORP", "THE", "AND", "FOR"):
            continue
        if 1 <= len(t) <= 5:
            return t
    return None


_LIQUID_UNIVERSE = (
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "AVGO", "TSLA", "AMD", "COST",
    "NFLX", "ADBE", "PEP", "CSCO", "INTU", "QCOM", "TXN", "AMAT", "MU", "PANW",
)


def _engine_candidate_cards(raw, limit=3, exclude: set[str] | None = None) -> list:
    """主菜不足时:先 EDGAR∩宇宙,再 indices/macro 锚定的流动性成分股补位。对冲标的不走此路径。"""
    today = datetime.date.today().isoformat()
    exclude = {str(x).upper() for x in (exclude or set())}
    pool = []
    for r in (raw or {}).get("results") or []:
        if not r.get("ok") or r.get("source") != "edgar_ma_8k":
            continue
        for it in r.get("items") or []:
            ticker = _ticker_from_edgar_company(str(it.get("company") or ""))
            if not ticker or ticker in _BAN or ticker in exclude:
                continue
            if not in_equity_universe(ticker):
                continue
            filed = str(it.get("filed") or "")[:10]
            pool.append((0 if filed == today else 1, filed, ticker, it))
    pool.sort(key=lambda x: (x[0], x[1] or "9999", x[2]))
    picks, seen = [], set()
    for _, filed, ticker, it in pool:
        if ticker in seen or len(picks) >= limit:
            continue
        seen.add(ticker)
        why_item = "%s · %s · filed %s" % (it.get("company"), it.get("form"), it.get("filed"))
        picks.append({
            "ticker": ticker,
            "direction": "call",
            "rank_reason": "【引擎补位】池内可锚定 EDGAR 条目中优先补位(弱催化·待复核排名理由)",
            "evidence": [{
                "source": "edgar",
                "item": why_item[:200],
                "why": ("【引擎补位·弱催化】仅 8-K 提交事实、无正文摘要——"
                        "开盘须确认才可执行,否则 abandon"),
            }],
            "key_levels": "无实盘报价·仅结构建议;开盘后15分钟站稳昨收上方再论(禁编具体价)",
            "strategy": {
                "type": "单腿 call",
                "strike_logic": "ATM 上一档(禁编权利金,以盘口为准)",
                "expiry": "0DTE",
                "entry_condition": "开盘后15–30分钟确认事件定价未一次性出尽,且未跳空低开>1%",
                "stop": "权利金 -30% 或跌破开盘15分钟低点",
                "abandon": "开盘即利空定价/跳空低开>1%/无成交量确认——弱催化直接作废",
                "t0_exit": "15:30 ET 前了结,不隔夜",
            },
        })
    if len(picks) >= limit:
        return picks
    # EDGAR 池内空/不足 → 用盘初 indices/宏观实读锚定流动性成分股(仍属采集证据,禁编报价)
    ammo = _hedge_ammo(raw if isinstance(raw, dict) else {"results": []})
    idx = {t.get("name"): t for t in (ammo.get("indices_tape") or []) if t.get("name")}
    fg = (ammo.get("fear_greed") or [{}])[0] if ammo.get("fear_greed") else {}
    spx = idx.get("SP500") or {}
    ndx = idx.get("NASDAQ") or {}
    vix = idx.get("VIX") or {}
    tape_line = (
        "SP500 chg=%s tape=%s close_loc=%s; NASDAQ chg=%s tape=%s; VIX chg=%s; fear_greed=%s(%s)"
        % (spx.get("chg_pct"), spx.get("tape_flag") or "—", spx.get("close_loc"),
           ndx.get("chg_pct"), ndx.get("tape_flag") or "—",
           vix.get("chg_pct"), fg.get("score"), fg.get("rating"))
    )
    rank_reasons = [
        "盘初流动性与期权深度最佳,便于 T+0 单腿 CALL 验证大盘承接",
        "对 NASDAQ/成长因子弹性更高,作第2观察名观察 beta 放大",
        "相对前两名弹性或板块暴露不同,作第3名分散观察",
    ]
    for ticker in _LIQUID_UNIVERSE:
        if len(picks) >= limit:
            break
        if ticker in seen or ticker in exclude or ticker in _BAN:
            continue
        if not in_equity_universe(ticker):
            continue
        seen.add(ticker)
        ri = len(picks)
        picks.append({
            "ticker": ticker,
            "direction": "call",
            "rank_reason": "【引擎补位·宏观锚定】" + rank_reasons[min(ri, 2)],
            "evidence": [{
                "source": "indices",
                "item": tape_line[:220],
                "why": ("池内 EDGAR 无足够成分股条目——以盘初指数/恐贪实读锚定流动性成分股观察;"
                        "非事件催化,开盘未确认则 abandon"),
            }],
            "key_levels": "跟随 SP500/NASDAQ 盘初高低点;无个股盘口则禁编具体价",
            "strategy": {
                "type": "单腿 call",
                "strike_logic": "ATM 上一档(禁编权利金,以盘口为准)",
                "expiry": "0DTE",
                "entry_condition": "开盘后15–30分钟指数未破盘初低且标的放量跟涨",
                "stop": "权利金 -30% 或跌破开盘15分钟低点",
                "abandon": "指数失守盘初低/无量假突破——宏观锚定观察直接作废",
                "t0_exit": "15:30 ET 前了结,不隔夜",
            },
        })
    return picks


def _assign_ranks(cands: list) -> list:
    """强制 rank=1..n 连续;缺 rank_reason 则补默认句(响亮)。"""
    out = []
    for i, c in enumerate(cands[:CANDIDATE_RANK_N]):
        if not isinstance(c, dict):
            continue
        c = dict(c)
        c["rank"] = i + 1
        rr = str(c.get("rank_reason") or "").strip()
        if not rr:
            c["rank_reason"] = (
                "【待补排名理由】相对其余候选的优先依据未写清——按输出顺序暂列 #%d" % (i + 1)
            )
            print("[scout] rank_reason 缺失 → 占位 #%d %s" % (i + 1, c.get("ticker")))
        out.append(c)
    return out


def ensure_candidates(data, raw=None, *, min_n=None):
    """主菜硬闸:恰 CANDIDATE_RANK_N 张;仅 SP500∪NDX;rank 1/2/3 + rank_reason。
    对冲腿不经此函数——宇宙过滤仅作用于 candidates。"""
    if not isinstance(data, dict):
        return data
    need = int(min_n if min_n is not None else CANDIDATE_RANK_N)
    cands = data.get("candidates") if isinstance(data.get("candidates"), list) else []
    data["candidates"] = cands
    uni = load_equity_universe()
    kept, dropped_ban, dropped_uni = [], [], []
    seen = set()
    for c in cands:
        if not isinstance(c, dict):
            continue
        t = str(c.get("ticker") or "").strip().upper().replace(".", "-")
        if not t or t in seen:
            continue
        if t in _BAN:
            dropped_ban.append(t)
            continue
        if t not in uni:
            dropped_uni.append(t)
            continue
        c["ticker"] = t
        seen.add(t)
        kept.append(c)
    if dropped_ban:
        print("[scout] 否决票剔除(不算主菜):", dropped_ban)
    if dropped_uni:
        print("[scout] 非 SP500∪Nasdaq100 剔除(对冲腿勿进 candidates):", dropped_uni)
    cands[:] = kept
    if len(cands) < need:
        filled = _engine_candidate_cards(
            raw, limit=need - len(cands), exclude={c["ticker"] for c in cands}
        )
        if filled:
            cands.extend(filled)
            tag = ("【引擎补位】主菜不足 %d/%d——"
                   "已用池内 EDGAR 补 %d 张弱证据卡,待复核"
                   % (len(cands) - len(filled), need, len(filled)))
            note = str(data.get("conclusion") or "")
            if "引擎补位" not in note:
                data["conclusion"] = ((note + " " + tag).strip() if note else tag)
            print("[scout]", tag, [c["ticker"] for c in filled])
    # 截断到 need,写 rank / rank_reason
    cands[:] = _assign_ranks(cands[:need])
    data["candidates"] = cands
    if len(cands) >= need:
        data["no_candidate_reason"] = ""
    else:
        data["no_candidate_reason"] = (
            "池内(SP500∪Nasdaq100)可锚定证据不足 %d/%d——已输出现有排名,"
            "禁止用池外微盘凑数;对冲腿另见 hedge" % (len(cands), need)
        )
        print("[scout] 【响亮】主菜排名不足:", len(cands), "/", need)
    return data


_RISK_RANK = {"低": 0, "中": 1, "高": 2}


def ensure_hedge(data, raw=None, cross=None):
    """v3.4 对冲铁律硬闸:hedge 永不空白;引擎风险地板;中/高缺腿 → 引擎补腿。"""
    if not isinstance(data, dict):
        return data
    hd = data.get("hedge")
    if not isinstance(hd, dict):
        data["hedge"] = {
            "distribution_risk": "低",
            "regime": "无明显风险",
            "basis": "DS 未输出 hedge 段——按铁律响亮补位为低,待复核",
            "legs": [],
            "note": "原稿缺 hedge;已禁止「什么都不写」",
        }
        print("[scout] hedge 段缺失 → 响亮补位")
        hd = data["hedge"]
    risk = str(hd.get("distribution_risk") or "").strip() or "低"
    # 引擎地板:三灯读数抬升 DS 过低的 distribution_risk
    cx = cross or {}
    hint = str(cx.get("distribution_hint") or "").strip()
    if hint in _RISK_RANK and _RISK_RANK.get(risk, 0) < _RISK_RANK[hint]:
        print("[scout] distribution_risk 地板抬升:", risk, "→", hint,
              "|", cx.get("distribution_basis"))
        risk = hint
        basis = str(hd.get("basis") or "")
        floor_tag = "【引擎地板】" + str(cx.get("distribution_basis") or hint)
        if floor_tag not in basis:
            hd["basis"] = (basis + " " + floor_tag).strip() if basis else floor_tag
        if hint in ("中", "高") and not str(hd.get("regime") or "").strip():
            hd["regime"] = "轮动"
        elif hint in ("中", "高") and hd.get("regime") in ("", "无明显风险", None):
            hd["regime"] = "轮动"
    hd["distribution_risk"] = risk
    legs = hd.get("legs") if isinstance(hd.get("legs"), list) else []
    hd["legs"] = legs
    if not (hd.get("basis") or hd.get("note") or legs):
        hd["note"] = "风险低暂不对冲(原稿空白已按铁律补 note)"
        print("[scout] hedge 内容全空 → 补 note")
    if risk in ("中", "高") and not legs:
        filled = _engine_hedge_legs(raw, limit=2)
        if filled:
            hd["legs"] = filled
            legs = filled
            tag = ("【引擎补位】DS 风险%s 但漏腿——已用 hedge_assets/indices 实测补 %d 条,待复核"
                   % (risk, len(filled)))
            hd["note"] = ((hd.get("note") or "") + " " + tag).strip()
            print("[scout]", tag)
        else:
            warn = "【响亮】风险%s 但 legs 为空且引擎无可用对冲读数——违反对冲铁律,待复核" % risk
            hd["note"] = ((hd.get("note") or "") + " " + warn).strip()
            print("[scout]", warn)
    # 风险低也必须有 note(铁律:永不空白)
    if risk == "低" and not str(hd.get("note") or "").strip():
        hd["note"] = "风险低暂不对冲——须引用引擎三灯/VIX/恐贪说明(原稿缺 note 已补)"
    # 入口卡 chip 依赖 regime——缺则按引擎/腿推断(不许长期 —)
    if not str(hd.get("regime") or "").strip():
        tickers = {str(x.get("ticker") or "").upper() for x in (hd.get("legs") or [])}
        overseas = tickers & {"FXI", "KWEB", "EWZ", "EWJ", "EEM", "BABA", "YINN"}
        if cx.get("liquidation_watch"):
            hd["regime"] = "全线下跌"
        elif overseas or (cx.get("rotation_divergence") or []):
            hd["regime"] = "资金迁徙(海外)"
        elif risk in ("中", "高"):
            hd["regime"] = "轮动"
        else:
            hd["regime"] = "无明显风险"
        print("[scout] hedge.regime 缺失 → 推断为", hd["regime"])
    data["hedge"] = hd
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


def _archive_prior_briefs(bdir: str, date: str, mode: str) -> None:
    """重跑累加:先把现用三件套挪到时间戳副本,禁止整份抹掉。"""
    stamp = datetime.datetime.now().strftime("%H%M%S")
    for name in (
        "%s-%s.md" % (date, mode),
        "%s-%s.html" % (date, mode),
        "%s-%s.json" % (date, mode),
        "%s_morning_task.md" % date if mode == "morning" else "",
        "%s-morning-final.md" % date if mode == "morning" else "",
        "%s-morning-final-expanded.md" % date if mode == "morning" else "",
        "%s-morning-final-glm.md" % date if mode == "morning" else "",
        "%s-morning-ab-compare.md" % date if mode == "morning" else "",
        "%s-evening-final.md" % date if mode == "evening" else "",
        "%s-evening-final-expanded.md" % date if mode == "evening" else "",
        "%s-evening-final-glm.md" % date if mode == "evening" else "",
        "%s-evening-ab-compare.md" % date if mode == "evening" else "",
    ):
        if not name:
            continue
        src = os.path.join(bdir, name)
        if not os.path.isfile(src):
            continue
        root, ext = os.path.splitext(name)
        dest = os.path.join(bdir, "%s.%s%s" % (root, stamp, ext))
        if os.path.exists(dest):
            dest = os.path.join(bdir, "%s.%s.%s%s" % (root, stamp, os.getpid(), ext))
        os.replace(src, dest)
        print("[scout] 归档前次(累加,非替代):", dest)


# ---- review/编译(本机接线:默认 EXPANDED,驳回 Aster;不改下方渲染器) ----
def review_origin_label(*, primary_label: str = "", expanded_meta: dict | None = None) -> str:
    """标明 review/编译真实来源(Lyra):
    - Grid 本地 substrate 编译 → expanded-本地
    - 借用 GLM 底座(glm52_cloud 等) → expanded-GLM
    以编排回执 substrate 为准,不以「走了 expanded 路由」冒充。
    """
    meta = expanded_meta or {}
    primary = (primary_label or "").strip().lower()
    sub = str(meta.get("substrate") or "").strip().lower()
    via = str(meta.get("via") or "")
    if meta.get("error") or via == "fallback_ds":
        return "ds(expanded失败)"
    # EXPANDED 编排回执:只认 local vs GLM 两种署名
    if sub.startswith("local"):
        return "expanded-本地"
    if "glm" in sub:
        return "expanded-GLM"
    if primary == "expanded" or via.startswith("b11:"):
        # 走了 EXPANDED 但 substrate 未回传——响亮标未知,禁止默认真 GLM
        return "expanded-未知"
    if primary == "glm":
        return "glm-直连"
    return "ds"


def build_review_prompt(
    mode: str, ds_draft: str, data, indices_snap, *, reviewer: str
) -> str:
    idx = json.dumps(indices_snap, ensure_ascii=False) if indices_snap else "无"
    if mode == "morning":
        must = (
            "上游已是 JSON 结构化晨会单(开盘后约15分钟·盘初 tape)。你输出更清晰的 Markdown 终稿给 Lyra:\n"
            "- 保留个股卡结构;默认 T+0 单腿 CALL;禁多腿;禁编权利金/假 $ 报价\n"
            "- 【指数实读】有 VIX close 时禁止写「VIX 缺失」,必须引用数字\n"
            "- 盘初口径:当日 chg_pct/tape_flag/close_loc 是部分K线,正文须标「盘初」,"
            "禁止写成全日收盘形态;挤兑硬判据留给晚报完整日线\n"
            "- SPY/QQQ 仅大盘环境;主菜=个股\n"
            "- synthetic GEX 不得洗成真盘\n"
            "- 主菜=恰3张个股卡,保留 rank 1/2/3 与 rank_reason;仅 SP500∪Nasdaq100\n"
            "- 对冲腿(贵金属/原油/海外ADR)不进个股宇宙,勿删 hedge\n"
            "- 禁止编造采集未出现的 ticker;禁编权利金\n"
            "- hedge 段永不空白:保留 distribution_risk/basis/legs 或 note"
        )
    else:
        must = (
            "上游是晚报 Markdown 参谋作业。你输出更清晰的 Markdown 终稿给 Lyra:\n"
            "- 严格保留 ## 分节:要闻催化 / 赔率变化 / 明日日历 / 明日方向 / 风险雷达\n"
            "- 风险雷达永不空白:命中拉高出货/资金迁徙/全线下跌须点名工具;未命中明写未见\n"
            "- 禁止补编采集中没有的数字;禁止编造个股催化\n"
            "- 分析作业≠下单指令;口径给 Lyra 拍板"
        )
    struct = json.dumps(data, ensure_ascii=False)[:9000] if data else ds_draft[:9000]
    return f"""你是 Scout 流水线的 review / 编译官({reviewer}),不是首席决策官。
Aster integrate 已驳回——你只做 review/编译,不扮演 Aster。
{must}
指数实读(权威):{idx}
—— DeepSeek 原稿 ——
{struct}
输出只要最终 Markdown 正文。"""

def build_glm_review_prompt(mode: str, ds_draft: str, data, indices_snap) -> str:
    return build_review_prompt(
        mode, ds_draft, data, indices_snap, reviewer="GLM 5.2 直连"
    )

def glm_review(mode: str, ds_draft: str, data, indices_snap) -> str:
    prompt = build_glm_review_prompt(mode, ds_draft, data, indices_snap)
    try:
        r = _http(
            GW + "/v1/chat/completions",
            {
                "model": GLM_MODEL,
                "max_tokens": 2200,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            timeout=300,
        )
        msg = (r.get("choices") or [{}])[0].get("message") or {}
        text = (msg.get("content") or "").strip()
        if not text:
            raise RuntimeError(
                "empty content finish=%s"
                % (r.get("choices") or [{}])[0].get("finish_reason")
            )
        print("[scout] GLM review/编译完成 %d 字符 model=%s" % (len(text), GLM_MODEL))
        return text
    except Exception as e:
        print("[scout] GLM review 失败(%s)→ 降级用 DS 原稿(响亮)" % e)
        return ds_draft

def expanded_review(mode: str, ds_draft: str, data, indices_snap) -> dict:
    """b11 STUDIO·EXPANDED 同链:POST 8515 /gateway/task/expanded。

    与 grid_workbench_b11 expandedOrchestrate 路径A 对齐:
      {task, memory_node, assets, client_context} → workbench 代签 → 8501 编排
    memory_node 用 scout-review,绝不写 workbench-b11。
    """
    if EXPANDED_MEMORY_NODE in {
        "workbench-b11",
        "cloud-glm52",
        "cloud-kimi",
        "field-particle",
    }:
        raise SystemExit(
            "[scout] SCOUT_EXPANDED_MEMORY_NODE=%s 禁止(生产记忆 RED LINE)"
            % EXPANDED_MEMORY_NODE
        )
    prompt = build_review_prompt(
        mode,
        ds_draft,
        data,
        indices_snap,
        reviewer="Grid EXPANDED 大底座 · GLM-5.2 substrate · 驳回 Aster integrate",
    )
    # 长任务 → expanded classify 走 document/heavy → 云端 glm52 substrate
    body = {
        "task": prompt,
        "memory_node": EXPANDED_MEMORY_NODE,
        "assets": [],
        "client_context": (
            "scout_%s_review · expanded GLM-5.2 · skip_aster_integrate"
            % (mode or "review")
        ),
        "cloud_enabled": True,
        "skip_aster_integrate": SKIP_ASTER_INTEGRATE,
    }
    if not SKIP_ASTER_INTEGRATE:
        raise SystemExit("[scout] SCOUT_SKIP_ASTER=0 已禁用——默认必须驳回 Aster(Lyra 拍板)")
    url = WB + "/gateway/task/expanded"
    try:
        r = _http(url, body, timeout=420)
        final = (r.get("final") or r.get("content") or "").strip()
        if not final:
            raise RuntimeError("expanded empty final keys=%s" % list(r.keys())[:12])
        prov = r.get("provenance") or {}
        meta = {
            "substrate": r.get("substrate"),
            "orchestrator": (prov.get("orchestrator") or r.get("orchestrator")),
            "envelope": prov.get("envelope_summary"),
            "memory_node": EXPANDED_MEMORY_NODE,
            "via": "b11:/gateway/task/expanded",
        }
        meta["review_origin"] = review_origin_label(
            primary_label="expanded", expanded_meta=meta
        )
        print(
            "[scout] EXPANDED review/编译完成 %d 字符 origin=%s substrate=%s orch=%s"
            % (len(final), meta.get("review_origin"), meta.get("substrate"),
               meta.get("orchestrator"))
        )
        return {"text": final, "meta": meta}
    except Exception as e:
        print("[scout] EXPANDED review 失败(%s)→ 降级用 DS 原稿(响亮)" % e)
        meta = {
            "error": str(e),
            "via": "fallback_ds",
            "memory_node": EXPANDED_MEMORY_NODE,
        }
        meta["review_origin"] = review_origin_label(
            primary_label="ds", expanded_meta=meta
        )
        return {"text": ds_draft, "meta": meta}


# ---- 渲染层:结构照抄 brief sample hedge;色板=白底灰框(禁全黑偷懒) ----
# 权威 UI 文件(已从 CloudDocs 样例结构生成,仅替换色板 token):
_UI_BRIEF = _HERE / "briefs" / "_ui_brief_sample_hedge_paper.html"

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
    rank = c.get("rank")
    rank_badge = ("#%s" % rank) if rank not in (None, "") else ""
    rows = []
    if rank_badge:
        rows.append(("排名", rank_badge))
    if c.get("rank_reason"):
        rows.append(("排名理由", c.get("rank_reason")))
    rows += [("形态", st.get("type")), ("行权价逻辑", st.get("strike_logic")),
             ("到期", st.get("expiry")), ("入场条件", st.get("entry_condition")),
             ("止损", st.get("stop")), ("作废条件", st.get("abandon")),
             ("T+0 平仓", st.get("t0_exit")), ("关键位", c.get("key_levels"))]
    kvs = "".join('<div class="kv"><b>%s</b><span>%s</span></div>' % (l, _esc(v)) for l, v in rows if v)
    badge_txt = ("%s %s" % (badge, rank_badge)).strip() if rank_badge and badge == "SCOUT" else badge
    return ('<div class="card"><span class="badge">%s %s</span>'
            '<div class="tick"><span class="sym">%s</span><span class="pill%s">%s</span></div>%s'
            '<details><summary>展开解析(证据出处)</summary>%s</details></div>'
            % (_esc(badge_txt), _esc(tag), _esc((c.get("ticker") or "?").upper()),
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
        # 按 rank 排序展示
        ordered = sorted(
            [c for c in cands if isinstance(c, dict)],
            key=lambda x: int(x.get("rank") or 99),
        )
        out.append('<section><h2>二 · 池内候选(排名1–3 · SP500∪Nasdaq · T+0 单腿 CALL)</h2>%s</section>'
                   % "".join(_cand_card(c, date) for c in ordered))
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
    lights = cross.get("distribution_lights") or {}
    def _yn(v):
        return "亮" if v else "灭"
    triad = ("指数冲高回落=%s · 恐贪极值=%s(score=%s) · GLD强势=%s"
             % (_yn(lights.get("index_distribution")),
                _yn(lights.get("fear_greed_extreme")),
                lights.get("fear_greed_score"),
                _yn(lights.get("gld_bid"))))
    rows = [("风险资产收跌", "%s / %s(%s)" % (cross.get("down_count"), cross.get("of"), downs)),
            ("VIX 日变动", "%s%%" % cross.get("vix_chg_pct")),
            ("TLT / UUP", "%s%% / %s%%" % (cross.get("tlt_chg_pct"), cross.get("uup_chg_pct"))),
            ("资金迁徙(海外领涨)", leaders),
            ("迁徙分化(美股跌而其涨)", div),
            ("tape flags", flags),
            ("出货三灯", triad),
            ("出货风险地板", "%s — %s" % (cross.get("distribution_hint") or "—",
                                   cross.get("distribution_basis") or "")),
            ("全线下跌判据", "触发——商品 call 不是对冲,海外也不是避风港" if liq else "未触发")]
    kvs = "".join('<div class="kv"><b>%s</b><span>%s</span></div>' % (l, _esc(v)) for l, v in rows)
    return '<section><h2>〇 · 跨资产引擎读数(确定性)</h2><div class="card">%s</div></section>' % kvs


def render_brief_html(date, mode, data, raw_text, cross=None, *, review_origin=""):
    warn = ""
    if (cross or {}).get("liquidation_watch"):
        warn = ('<div class="banner" style="border-color:var(--red)">'
                '<b style="color:var(--red)">全线下跌 WATCH</b>'
                '<span>风险资产 %s/%s 收跌 · VIX %s%% · 商品 call 不是对冲</span></div>'
                % (_esc(cross.get("down_count")), _esc(cross.get("of")), _esc(cross.get("vix_chg_pct"))))
    origin = (review_origin or "").strip()
    origin_chip = (
        '<div class="banner"><b>review/编译</b><span class="num">%s</span></div>'
        % _esc(origin)
    ) if origin else ""
    body = (warn + origin_chip + _engine_card(cross)
            + (_render_structured(date, data) if data else _md_fallback(raw_text)))
    sub = ("%s · %s · review %s · 参谋作业,Lyra 拍板" % (mode, date, origin)
           if origin else "%s · %s · 参谋作业,Lyra 拍板" % (mode, date))
    return ('<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"/>'
            '<meta name="viewport" content="width=device-width,initial-scale=1"/>'
            '<title>SCOUT · %s · %s</title><style>%s</style></head><body>'
            '<header><h1>SCOUT</h1><span class="sub">%s</span></header>'
            '%s<footer>build scout v3.3 · DS 决策官 JSON 结构化 · 无证据不点名 · 合成 GEX 不作数 · '
            '渲染:_render_structured/_cand_card/_md_fallback</footer></body></html>'
            % (mode.upper(), _esc(date), BRIEF_CSS, _esc(sub), body))


def render_console(title, body, date, mode, data=None, cross=None, *, review=None):
    """DS 作业进 console 落档;HTML/JSON 用 DS structured(+_engine)。review 只写 md/终稿,不改渲染器。"""
    review = review or {}
    ds_id = glm_id = None
    payload_doc = ("[DS 决策官作业·JSON(EXPANDED review/编译直接吃)] "
                   + json.dumps(data, ensure_ascii=False)[:8000]) if data else \
                  ("[DS 决策官作业,存档] " + body[:8000])
    try:
        if not CONSOLE_KEY:
            raise RuntimeError("CONSOLE_KEY 未配置")
        t = _http(CONSOLE + "/api/tasks",
                  {"workspace": "trade", "title": title + " · DS原稿", "owner_node": "deepseek_lane",
                   "risk_level": "read", "io_contract": payload_doc},
                  {"X-Console-Key": CONSOLE_KEY})
        ds_id = t.get("task_id")
        print("[scout] console 任务 DS#%s(work_log 入魂器)" % ds_id)
        exp = (review.get("expanded_final") or "").strip()
        if exp:
            t2 = _http(
                CONSOLE + "/api/tasks",
                {
                    "workspace": "trade",
                    "title": title + " · EXPANDED终稿",
                    "owner_node": "glm_lane",
                    "risk_level": "read",
                    "deps": [ds_id] if ds_id else [],
                    "io_contract": "[EXPANDED review 编译终稿,存档] mode=%s\n%s" % (mode, exp[:8000]),
                },
                {"X-Console-Key": CONSOLE_KEY},
            )
            glm_id = t2.get("task_id")
            print("[scout] console EXPANDED#%s" % glm_id)
    except Exception as e:
        print("[scout] console 不可达(%s)→ 本地落盘" % e)
    bdir = os.path.join(OUT, "briefs")
    os.makedirs(bdir, exist_ok=True)
    _archive_prior_briefs(bdir, date, mode)
    bp = os.path.join(bdir, "%s-%s.md" % (date, mode))
    sections = ["# %s\n" % title]
    exp = (review.get("expanded_final") or "").strip()
    glm = (review.get("glm_final") or "").strip()
    meta = review.get("expanded_meta") or {}
    origin = review_origin_label(
        primary_label=str(review.get("primary_label") or ""),
        expanded_meta=meta,
    )
    if meta and not meta.get("review_origin"):
        meta["review_origin"] = origin
    if exp:
        sections.append(
            "## EXPANDED 终稿(b11 STUDIO·EXPANDED 大底座 review/编译)\n\n"
            "review_origin=%s · via=%s · substrate=%s · orch=%s · memory_node=%s\n\n%s\n"
            % (origin, meta.get("via"), meta.get("substrate"), meta.get("orchestrator"),
               meta.get("memory_node"), exp)
        )
    if glm:
        sections.append("## GLM 直连终稿(8501 /v1 · %s)\n\n%s\n" % (GLM_MODEL, glm))
    if not exp and not glm:
        sections.append("## DS 原稿(无 review)\n\n%s\n" % body.strip())
    else:
        sections.append("---\n\n## DS 原稿(对照 · 勿当终稿)\n\n%s\n" % body.strip())
    text = "\n".join(sections)
    with open(bp, "w", encoding="utf-8") as f:
        f.write(text)
    primary = exp or glm or body
    # 晨会 HTML 吃 DS structured;晚报无 JSON → HTML 展示 EXPANDED 终稿(有则优先)
    html_src = body if data is not None else primary
    hp = os.path.join(bdir, "%s-%s.html" % (date, mode))
    with open(hp, "w", encoding="utf-8") as f:
        f.write(render_brief_html(
            date, mode, data, html_src, cross, review_origin=origin
        ))
    review_blob = {
        "primary": review.get("primary_label") or "ds",
        "review_origin": origin,
        "glm_chars": len(glm),
        "expanded_chars": len(exp),
        "expanded_meta": meta,
        "skip_aster_integrate": SKIP_ASTER_INTEGRATE,
    }
    if data is not None:
        with open(os.path.join(bdir, "%s-%s.json" % (date, mode)), "w", encoding="utf-8") as f:
            json.dump(
                {"_engine": cross, "ds": data, "review": review_blob},
                f,
                ensure_ascii=False,
                indent=1,
            )
    elif mode == "evening" and cross is not None:
        # 晚报无 DS JSON,仍落 _engine+review 供入口/审计(累加)
        with open(os.path.join(bdir, "%s-%s.json" % (date, mode)), "w", encoding="utf-8") as f:
            json.dump({"_engine": cross, "review": review_blob}, f, ensure_ascii=False, indent=1)
    if mode == "morning":
        with open(os.path.join(bdir, "%s_morning_task.md" % date), "w", encoding="utf-8") as f:
            f.write(text)
        with open(os.path.join(bdir, "%s-morning-final.md" % date), "w", encoding="utf-8") as f:
            f.write("# %s\n\n%s\n" % (title, primary.strip()))
        if exp:
            with open(os.path.join(bdir, "%s-morning-final-expanded.md" % date),
                      "w", encoding="utf-8") as f:
                f.write("# %s · EXPANDED\n\n%s\n" % (title, exp))
        if glm and exp:
            with open(os.path.join(bdir, "%s-morning-ab-compare.md" % date),
                      "w", encoding="utf-8") as f:
                f.write(
                    "# Scout review A/B · %s\n\n"
                    "## A · GLM 直连 (`%s`)\n\n%s\n\n---\n\n"
                    "## B · b11 STUDIO·EXPANDED\n\n%s\n"
                    % (date, GLM_MODEL, glm, exp)
                )
    elif mode == "evening":
        with open(os.path.join(bdir, "%s-evening-final.md" % date), "w", encoding="utf-8") as f:
            f.write("# %s\n\n%s\n" % (title, primary.strip()))
        if exp:
            with open(os.path.join(bdir, "%s-evening-final-expanded.md" % date),
                      "w", encoding="utf-8") as f:
                f.write("# %s · EXPANDED\n\n%s\n" % (title, exp))
        if glm and exp:
            with open(os.path.join(bdir, "%s-evening-ab-compare.md" % date),
                      "w", encoding="utf-8") as f:
                f.write(
                    "# Scout evening review A/B · %s\n\n"
                    "## A · GLM 直连 (`%s`)\n\n%s\n\n---\n\n"
                    "## B · b11 STUDIO·EXPANDED\n\n%s\n"
                    % (date, GLM_MODEL, glm, exp)
                )
    print("[scout] 落盘:", bp, "+", hp, "(+json)" if data is not None or mode == "evening" else "")
    return bp, ds_id, glm_id


def emit_aether_scout(
    date, mode, title, primary, bp, *,
    ds_draft="", expanded_final="", expanded_meta=None, glm_final="",
    primary_label="expanded", ds_task_id=None, glm_task_id=None,
    data=None, cross=None, ws=None,
):
    payload = {
        "date": date,
        "mode": mode,
        "title": title,
        "body": primary,
        "glm_final": glm_final or "",
        "expanded_final": expanded_final or "",
        "expanded_meta": expanded_meta or {},
        "primary_review": primary_label,
        "review_origin": review_origin_label(
            primary_label=primary_label, expanded_meta=expanded_meta or {}
        ),
        "ds_draft": ds_draft or "",
        "via": "scout_v3_6_ds_expanded",
        "brief_path": bp,
        "workstation": ws,
        "console_ds_task": ds_task_id,
        "console_glm_task": glm_task_id,
        "pipeline": "DS JSON→EXPANDED(skip Aster)·v3.6 cross-asset",
        "review_default": DEFAULT_REVIEW,
        "skip_aster_integrate": SKIP_ASTER_INTEGRATE,
        "structured": {"_engine": cross, "ds": data} if data is not None else None,
        "liquidation_watch": bool((cross or {}).get("liquidation_watch")),
        "regime": ((data or {}).get("hedge") or {}).get("regime") if isinstance(data, dict) else None,
    }
    data_b = json.dumps(
        {"source": "aether", "kind": "aether_scout_brief", "payload": payload},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        GW + "/store/events",
        data=data_b,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            print("[scout] aether OPTION emit",
                  "ok" if 200 <= resp.status < 300 else resp.status)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print("[scout] aether emit 失败(响亮):", e)


def _raw_ok_count(path: str) -> int:
    try:
        j = json.load(open(path, encoding="utf-8"))
        return sum(1 for r in (j.get("results") or []) if r.get("ok"))
    except Exception:
        return -1


def _pick_day_raw(raw_dir: str, day: str) -> str | None:
    """同日 raw 选优:ok 源数优先,同 ok 再比 mtime。0-ok 的 SSL 失败稿不得盖掉好稿。"""
    cands = []
    canonical = os.path.join(raw_dir, day + ".json")
    if os.path.isfile(canonical):
        cands.append(canonical)
    try:
        for name in os.listdir(raw_dir):
            if name.startswith(day + "-") and name.endswith(".json"):
                cands.append(os.path.join(raw_dir, name))
    except OSError:
        pass
    if not cands:
        return None
    cands.sort(key=lambda p: (_raw_ok_count(p), os.path.getmtime(p)), reverse=True)
    return cands[0]


def _pick_today_raw(raw_dir: str, today: str) -> str | None:
    """今日 raw 选优(与昨日对比共用 _pick_day_raw)。"""
    return _pick_day_raw(raw_dir, today)


def main():
    ap = argparse.ArgumentParser(description="Scout Agent v3.6(DS→默认 EXPANDED,驳回Aster)")
    ap.add_argument("--mode", choices=["evening", "morning"], default="evening")
    ap.add_argument("--dry-run", action="store_true")
    # 默认复用 raw(本机 SSL/墙常让全采 0/9);要重采显式 --fetch
    ap.add_argument("--fetch", action="store_true",
                    help="强制重采网络源;默认复用今日 raw(或 SCOUT_SKIP_FETCH=1)")
    ap.add_argument("--skip-fetch", action="store_true",
                    help="兼容旧开关(=默认行为:有 raw 则复用)")
    ap.add_argument("--review", choices=["glm", "expanded", "both", "none"],
                    default=os.getenv("SCOUT_REVIEW", DEFAULT_REVIEW),
                    help="review:expanded=默认B(驳回Aster);both=GLM A/B(仅显式要求时)")
    a = ap.parse_args()
    today = datetime.date.today().isoformat()
    raw_dir = os.path.join(OUT, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    raw_path = os.path.join(raw_dir, today + ".json")
    env_skip = os.getenv("SCOUT_SKIP_FETCH", "1").strip().lower() not in ("0", "false", "no")
    force_fetch = bool(a.fetch) or os.getenv("SCOUT_FORCE_FETCH", "").strip() in ("1", "true", "yes")
    prefer_raw = (a.skip_fetch or env_skip) and not force_fetch
    picked = _pick_today_raw(raw_dir, today)

    if prefer_raw and picked:
        payload = json.load(open(picked, encoding="utf-8"))
        raw_path = picked
        print("[scout] 默认复用 raw(%d ok) → %s  (重采请加 --fetch)"
              % (_raw_ok_count(picked), picked))
    else:
        results = fetchers.run_all()
        payload = {"results": results, "skips": fetchers.SKIPS}
        stamp_path = raw_path
        if os.path.exists(raw_path):
            stamp_path = raw_path.replace(
                ".json", "-" + datetime.datetime.now().strftime("%H%M") + ".json"
            )
        json.dump(payload, open(stamp_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        # 成功采写回 canonical;全失败则不盖掉好 raw
        ok = sum(1 for r in payload["results"] if r["ok"])
        print("[scout] %s 源成功 %d/%d → %s" % (today, ok, len(payload["results"]), stamp_path))
        for b in payload["results"]:
            if not b["ok"]:
                print("   ✗", b["source"], b.get("error", ""))
        if ok > 0:
            if stamp_path != raw_path:
                json.dump(payload, open(raw_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                print("[scout] 写回 canonical raw →", raw_path)
        else:
            fallback = _pick_today_raw(raw_dir, today)
            # stamp 刚写入的 0-ok 也在目录里——挑 ok>0 的
            best = None
            best_n = 0
            for name in os.listdir(raw_dir):
                if not (name.startswith(today) and name.endswith(".json")):
                    continue
                p = os.path.join(raw_dir, name)
                if p == stamp_path:
                    continue
                n = _raw_ok_count(p)
                if n > best_n:
                    best_n, best = n, p
            if best and best_n > 0:
                payload = json.load(open(best, encoding="utf-8"))
                raw_path = best
                print("[scout] 全采失败 → 回退复用 raw(%d ok) %s" % (best_n, best))
            else:
                print("[scout] 全采失败且无可用 raw——继续空弹药(响亮)")

    if a.dry_run:
        print("[scout] --dry-run 止步于采集"); return

    yday = yesterday_raw(today)
    cross = cross_asset_summary(payload)
    print("[scout] 引擎 cross down=%s/%s liq=%s tape=%s"
          % (cross.get("down_count"), cross.get("of"), cross.get("liquidation_watch"),
             list((cross.get("tape_flags") or {}).keys())[:6]))
    if cross.get("liquidation_watch"):
        print("[scout] 引擎:全线下跌判据触发", cross)
    def _pick_primary(review, body, glm_final, expanded_final, expanded_meta):
        exp_ok = bool(expanded_final) and not str(
            expanded_meta.get("substrate") or ""
        ).endswith("_error") and not expanded_final.startswith("cloud 不可用")
        if review == "expanded" and exp_ok:
            return expanded_final, "expanded"
        if review == "glm":
            return glm_final or body, "glm"
        if review == "both" and exp_ok:
            return expanded_final, "expanded"
        if review == "both":
            return glm_final or body, "glm"
        return body, "ds"

    def _run_review(mode, body, data):
        """晨会/晚报共用:默认 EXPANDED,驳回 Aster;显式 both 才 GLM A/B。"""
        glm_final = ""
        expanded_final = ""
        expanded_meta = {}
        if a.review in ("glm", "both"):
            glm_final = glm_review(mode, body, data, {})
        if a.review in ("expanded", "both"):
            if not SKIP_ASTER_INTEGRATE:
                raise SystemExit("[scout] SCOUT_SKIP_ASTER=0 已禁用——evening/morning 均须驳回 Aster")
            er = expanded_review(mode, body, data, {})
            expanded_final = er.get("text") or ""
            expanded_meta = er.get("meta") or {}
            print("[scout] EXPANDED meta(%s)" % mode, expanded_meta)
        primary, primary_label = _pick_primary(
            a.review, body, glm_final, expanded_final, expanded_meta
        )
        return glm_final, expanded_final, expanded_meta, primary, primary_label

    if a.mode == "morning":
        ws = fetch_workstation_state()
        egaps = engine_data_gaps(payload, yday, ws)
        print("[scout] 引擎 data_gaps:", json.dumps(egaps, ensure_ascii=False)[:400])
        title = "Scout 晨会交易任务单 · " + today
        print("[scout] DS 决策官(JSON) · review=%s…" % a.review)
        body = ds_call(build_trading_prompt(payload, ws, yday, cross, engine_gaps=egaps))
        data = _extract_json(body)
        if data is None:
            print("[scout] DS 未按 JSON schema 输出——晨会单降级为文本分节渲染(响亮记录)")
            data = {"data_gaps": egaps, "candidates": [], "hedge": {},
                    "conclusion": "DS JSON 解析失败——仅引擎缺口入档"}
            data = ensure_hedge(data, payload, cross)
            data = ensure_candidates(data, payload, min_n=CANDIDATE_RANK_N)
            data = ensure_data_gaps(data, egaps)
        else:
            data = ensure_hedge(data, payload, cross)
            data = ensure_candidates(data, payload, min_n=CANDIDATE_RANK_N)
            data = ensure_data_gaps(data, egaps)
        glm_final, expanded_final, expanded_meta, primary, primary_label = _run_review(
            "morning", body, data
        )
        bp, ds_id, glm_id = render_console(
            title, body, today, "morning", data, cross,
            review={
                "expanded_final": expanded_final if a.review in ("expanded", "both") else "",
                "glm_final": glm_final if a.review in ("glm", "both") else "",
                "expanded_meta": expanded_meta,
                "primary_label": primary_label,
            },
        )
        emit_aether_scout(
            today, "morning", title, primary, bp,
            ds_draft=body, expanded_final=expanded_final, expanded_meta=expanded_meta,
            glm_final=glm_final if a.review in ("glm", "both") else "",
            primary_label=primary_label, ds_task_id=ds_id, glm_task_id=glm_id,
            data=data, cross=cross, ws=ws,
        )
    else:
        title = "Scout 晚报复盘 · " + today
        print("[scout] DS 决策官(晚报 Markdown) · review=%s · skip_aster=%s…"
              % (a.review, SKIP_ASTER_INTEGRATE))
        body = ds_call(build_evening_prompt(payload, yday, cross))
        glm_final, expanded_final, expanded_meta, primary, primary_label = _run_review(
            "evening", body, None
        )
        bp, ds_id, glm_id = render_console(
            title, body, today, "evening", None, cross,
            review={
                "expanded_final": expanded_final if a.review in ("expanded", "both") else "",
                "glm_final": glm_final if a.review in ("glm", "both") else "",
                "expanded_meta": expanded_meta,
                "primary_label": primary_label,
            },
        )
        emit_aether_scout(
            today, "evening", title, primary, bp,
            ds_draft=body, expanded_final=expanded_final, expanded_meta=expanded_meta,
            glm_final=glm_final if a.review in ("glm", "both") else "",
            primary_label=primary_label, ds_task_id=ds_id, glm_task_id=glm_id,
            data=None, cross=cross, ws=None,
        )


if __name__ == "__main__":
    main()
