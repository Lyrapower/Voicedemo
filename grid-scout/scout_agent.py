#!/usr/bin/env python3
"""scout_agent.py —— Scout Agent v3.25(DS 决策官 · 三班制+BMO 伏击,守恒手写)
合流(v3.15 判例,两支并集零取舍):
  守恒支线 v3.17-3.23:四槽卡/趋势引擎/量能·隔夜日内/Grid 降噪/账本卫生/影子 lane
  现场支线 v3.16.x(verify 契约全员回岗):think=False / emit_aether_scout /
  rsi14_tape / tape_check / 晚班源清单+lint 硬闸 / EXPANDED-GLM review / et_now_hm /
  amc cap 30 / yday 4000 / RSI 禁自估
数据层:FMP 主源 → ThetaData 第二源 → Alpaca backup(fetchers v3.24),stooq 已移除。
四班(v3.25,Lyra 拍板 2026-08-19):morning 6:45(不含财报,带交班)/ midday 10:40
(定位复核+AMC 初筛)/ earnings 12:35(开卷财报班:今晚 AMC + 次日 BMO 双伏击)/
evening 9pm(三班合并复盘+明日弹药)。
建议 ≠ 自动信号:DS 出的是给 Lyra 看的决策官作业,Lyra 自己拍板买不买。
"""
from __future__ import annotations
import argparse, datetime, html, json, os, re, sys, urllib.request


def _load_env_file():
    """读脚本目录 .env(KEY=VAL)进环境,不覆盖已有值。v3.24:必须先于 import fetchers
    与下方常量——DEEPSEEK_API_KEY/CONSOLE_KEY/OUT 均为 import 期快照,晚于此处加载的
    .env 全是死键(8-17 手动重跑 key 不生效 + 写错目录双坑的共同根)。"""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(p):
        return
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env_file()

import fetchers

DS_BASE = os.getenv("DEEPSEEK_BASE", "https://api.deepseek.com")
DS_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
CONSOLE = os.getenv("CONSOLE_URL", "http://localhost:8610")
OWS = os.getenv("OWS_URL", "http://localhost:8620")
GW = os.getenv("GATEWAY_URL", "http://127.0.0.1:8501").rstrip("/")
WB = os.getenv("WORKBENCH_URL", "http://127.0.0.1:8515").rstrip("/")
# OUT 默认=脚本所在目录(装哪跑哪)——~/grid-scout 死默认曾致手动重跑写错根(8-17,
# 与 land/verify 硬编码 Projects/demo/grid-scout 的双根陷阱就此拆除);env SCOUT_OUT 仍最高。
OUT = os.getenv("SCOUT_OUT", os.path.dirname(os.path.abspath(__file__)))


def _http(url, body=None, headers=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    # SSL 族收尾:fetchers._get 与本函数是全部两条网缝,同挂 certifi 上下文(8-17 根因)
    with urllib.request.urlopen(req, timeout=timeout, context=fetchers._ssl_context()) as r:
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


def _slim_raw(payload, budget=None):
    """prompt 供数瘦身(v3.24):剥引擎私有键(_rets20 等,20 组浮点×30 资产≈5KB 纯噪声),
    预算 18000(env RAW_PROMPT_CHARS)——旧 6000 按源序切,polymarket(概率词唯一合法
    来源)/财报日历未来日(S2a run-up 原料)/sectors 排在刀口后,从未进过 DS 视野。"""
    budget = budget or int(os.getenv("RAW_PROMPT_CHARS", "18000"))
    slim = []
    for src_ in payload.get("results", payload.get("sources", [])) or []:
        items = [({k: v for k, v in it.items() if not str(k).startswith("_")}
                  if isinstance(it, dict) else it) for it in src_.get("items", [])]
        slim.append({**{k: v for k, v in src_.items() if k != "items"}, "items": items})
    return json.dumps({"results": slim, "skips": (payload.get("skips") or [])[:12]},
                      ensure_ascii=False)[:budget]


# ---- DS 决策官 prompt(v3.2 池化:大盘方向+池内提名) ----
_SHIFT_TITLE = {"morning": "晨会交易任务单", "midday": "盘中复核单", "earnings": "财报班任务单"}
_SHIFT_CLOCK = {
    "morning": "(晨班定时 9:45 ET=开盘后约 15 分钟;手动重跑以钟点为准)",
    "midday": "(盘中班定时 13:40 ET;手动重跑以钟点为准)",
    "earnings": "(财报班定时 15:35 ET=收盘前约 25 分钟;手动重跑以钟点为准)"}
_SHIFT_DATA_DESC = {"morning": "隔夜数据 + 盘初 tape", "midday": "盘中 tape 与今晨在案腿",
                    "earnings": "近全日 tape 与财报日历(开卷:当日两班数据已在手)"}
_SHIFT_TAPE_NOTE = {
    "morning": "indices/hedge_assets 的当日行是盘初部分K线(开盘~15分钟,非收盘),\nchg_pct 是盘初对昨收,tape_flag/close_loc 按盘初形态解读,不当全日形态用;",
    "midday": "当日行是盘中K线(开盘~4小时,非收盘),chg_pct 是盘中对昨收,\ntape_flag/close_loc 按盘中形态解读,不当全日形态用;",
    "earnings": "当日行已接近全日K线(收盘前约25分钟),chg_pct 接近全日涨跌,\nclose_loc 接近收盘形态,可当日内定型读;"}


def _s2_section(shift):
    """S2 槽分班文本(v3.25 三班制,Lyra 拍板 2026-08-19:06:45 班不含财报)。"""
    if shift in ("morning", "midday"):
        extra = ("\n   另:对引擎 amc_tonight 名单给初筛意见(按名单序前三点名+双杀预检),"
                 "写进 conclusion,不占槽、不建仓" if shift == "midday" else "")
        return ("S2 财报槽(本班停用):财报内容整体移至 12:45 财报班(Lyra 2026-08-19 拍板)。\n"
                "   本槽一律输出空槽卡(empty=true, empty_reason=\"财报腿在 12:45 财报班\");\n"
                "   本班不评估、不推荐任何财报驱动腿——财报票即使异动也不入候选,留待财报班" + extra)
    return ("S2 财报伏击·今晚 AMC(财报班主攻位一):amc_tonight 名单择一,~12:50 PST 尾盘买入,\n"
            "   持过财报,次日盘初按结果处置(gap-and-go 续持/开盘即走);earnings_note 必须\n"
            "   含\"持过财报,IV crush 风险自担\"字样(次晨交班块靠\"持过财报\"识别过夜腿);\n"
            "   无合格 AMC 标的时本槽回落 run-up 腿:upcoming_earnings 名单(未来 2-8 个交易日,\n"
            "   引擎已附读数)择一吃预期消化段,公布前必须离场(手册第二步);\n"
            "   双杀排除硬规则(AMD/NVDA 型大热禁入):实测 chg5_pct>15% 或 rsi14>75\n"
            "      = 利好已定价、多空双杀高发,机械禁入;AI 巨头共识热票(AMD/NVDA/TSLA 级)禁入;\n"
            "      选预期温和、IV 未过热的中大盘\n"
            "   已出结果的财报票(今晨 BMO/昨夜 AMC gap)不属本槽——由 movers 硬闸强制显式处理,\n"
            "      够强则进 S1;\n"
            "   evidence 硬规则:必须引用所属板块当日读数(sector_leaders/sector_laggards 的 chg_pct/mom20),\n"
            "      候选板块与 sector_leaders 背离时必须在 rank_reason 写一句解释(为何逆板块仍做)")


def _s4_section(shift):
    base = ("S4 引擎位:由跨资产引擎读数驱动——领涨板块龙头、迁徙腿(divergence 证实)或\n"
            "   对冲腿(按 regime),evidence 必须引用引擎数字")
    if shift != "earnings":
        return base
    return ("S4 财报伏击·明日 BMO(财报班主攻位二;v3.25 新腿,Lyra 拍板 2026-08-19,EL 案根治):\n"
            "   bmo_tomorrow 名单(明日盘前出结果,引擎已附读数)择一,~12:50 PST 尾盘买入,\n"
            "   持过夜至明晨出数,明晨盘初按结果处置;earnings_note 必须含\"持过财报,\n"
            "   IV crush 风险自担\";双杀排除硬规则同 S2;无合格 BMO 标的时本槽回落引擎位\n"
            "   (领涨板块龙头/迁徙腿/对冲腿,evidence 引用引擎数字)\n"
            "   过夜敞口规则(默认,Lyra 可改):S2 与 S4 两条伏击腿只择一执行——两卡并排给出,\n"
            "   rank/rank_reason 写清优先序与对比理由,买哪条交易员拍板;两条都建=过夜敞口翻倍,禁默认;\n"
            "   evidence 硬规则:必须引用所属板块当日读数(sector_leaders/sector_laggards 的 chg_pct/mom20),\n"
            "      候选板块与 sector_leaders 背离时必须在 rank_reason 写一句解释(为何逆板块仍做)")


def _movers_gate(shift):
    if shift == "earnings":
        return ("主菜优先级(堵\"抓小众漏大鱼\",TEAM 案例后立):\n"
                "- 引擎 earnings_movers 榜首 |chg_pct|≥8% 的标的必须显式处理——进 candidates 评估,\n"
                "  或进 rejected 写明理由;禁止无痕跳过\n")
    return "板块对齐(主菜优先级同源规则):\n"


def _earnings_rulebook(shift):
    if shift != "earnings":
        return ("财报手册本班停用——一切财报腿/手册在 12:45 财报班。候选若 5 个交易日内撞财报,\n"
                "仍须在 earnings_note 写明日期/BMO 或 AMC(信息披露),但本班禁做财报驱动腿。")
    return """财报两步手册(earnings_calendar 采集必须核对;候选撞财报必须在 earnings_note 声明):
- 第一步·财报/重大消息当日:禁开盘第一根追入——高 IV + 双向扫损 = 多空双杀;
  合法入场 = IV crush 落地后、盘初区间(约首30分钟)方向突破确认再进,0DTE 此时才合法
- 第二步·财报前 run-up(公布前 2-8 个交易日):可做预期抢跑 call,买"预期+IV 双升"
  (vega 顺风);硬规则 = 财报公布前必须离场,赚 run-up 不赌事件;
  今日 AMC 出财报的标的,T+0 收盘前清仓(本来就是纪律,此处双重锁死)
- 第三步·财报次日(昨夜 AMC 已出结果,今晨 gap):IV 已 crush——单腿 call 的黄金窗口之一;
  gap-and-go = 盘初 30 分钟站稳开盘价上方再追;首 30 分钟回补 gap 过半 = fade,放弃做多;
  方向已被结果定调,禁逆结果抄底/摸顶
- 候选 5 个交易日内有财报 → earnings_note 写明日期/BMO 或 AMC/采用哪条手册;无则写"无"
今晚 AMC 规则(引擎 amc_tonight 名单必须核对,读数已附 rsi14/chg5_pct):
- 名单内标的走 S2 尾盘伏击腿(~12:50 PST 买入持过财报)或不做;
  除 S2/S4 伏击腿外禁持仓过财报;双杀排除硬规则先于一切(chg5>15% 或 rsi>75 机械禁入)
- 点不点名是 DS 的判断;但名单前三(按市值)未点名时,须在 rejected 或正文给一句理由
明日 BMO 规则(引擎 bmo_tomorrow 名单必须核对,读数已附 rsi14/chg5_pct):
- 名单内标的走 S4 BMO 伏击腿或不做;双杀排除硬规则先于一切;
- 名单前三(按名单序)未点名时,须在 rejected 或正文给一句理由
未来财报 run-up(引擎 upcoming_earnings,未来 2-8 个交易日,cap 12,前 8 附读数):
- 作 S2 回落位供数;有预期消化段证据的票优先;公布前必须离场"""


def _shift_block(shift, todays):
    parts = []
    if shift == "morning":
        parts.append("昨夜交班义务(v3.25):引擎读数 handover 块 = 昨夜过夜伏击腿与昨日 watch 的盘初实测。"
                     "overnight_legs 必须首屏逐腿处置(gap-and-go 续持/开盘即走,写进 macro.logic 或对应候选);"
                     "watch_tape 有显著变化(|chg_pct|≥3%)的必须点名;昨日战绩 rejected_review 里 "
                     "flag_misskill=true(被否却涨>2%)的必须一句话复盘误杀原因。")
        parts.append("本班纪律:不出财报腿——财报评估、AMC/BMO 伏击、run-up 全部在 12:45 财报班。")
    elif shift == "midday":
        parts.append("本班定位(盘中复核班):①逐腿复核今晨在案腿(见下方在案腿)——持有/止损/离场校正,"
                     "写进对应槽 note 或 conclusion;②主池盘中动量点名——S1/S4 仅在动量显著时给新卡,默认收敛;"
                     "③今晚 AMC 初筛(见 S2 说明)。本班默认不建新仓——出新卡必须写明为何等不到财报班。")
    else:
        parts.append("本班定位(财报班,开卷):当日数据已全。主攻两腿 = S2 今晚 AMC 伏击 + S4 明日 BMO 伏击,"
                     "入场窗同为 12:50-12:55 PST 尾盘;两腿并排、只择一执行(过夜敞口规则见 S4);"
                     "upcoming_earnings(2-8 日窗)为 S2 回落位供数。今晨/盘中在案腿只做收尾提示(13:00 收盘硬平仓),不重复出卡。")
    if todays:
        parts.append("今日已出班次在案腿:" + json.dumps(todays, ensure_ascii=False)[:1600])
    return "\n".join(parts)


def build_trading_prompt(raw, ws, yday, cross=None, prev=None, shift="morning", todays=None):
    return f"""你是交易台的首席决策官。当前 {fetchers.et_now_hm()} ET
{_SHIFT_CLOCK[shift]},
基于{_SHIFT_DATA_DESC[shift]}给出清晰的分析作业
(这是给交易员参考的分析,交易员自己拍板执行,不是自动下单)。
观察宇宙(2026-08-06 扩定,三层):
A. S&P 500 与 Nasdaq 成分池(主池,不是 SPY/QQQ 两只 ETF)
B. 事件驱动个股不限成分——8-K 并购/FDA 等隔夜证据命中的美股可点名,但必须过流动性闸:
   大中盘、期权活跃;小盘或期权价差宽的宁可不点,T+0 会死在价差上
C. 海外 ADR 巨头(BABA/PDD/JD/TSM/NVO 级别)——迁徙或自身事件驱动时可点,
   时差跳空风险写进 abandon
每个候选必须填 liquidity 字段:一句话说明流动性为何扛得住 T+0。
读数口径提醒:{_SHIFT_TAPE_NOTE[shift]}
昨日完整形态看晚报与昨日采集。

隔夜采集:{_slim_raw(raw)}
工作站读数(GEX/特征):{json.dumps(ws, ensure_ascii=False) if ws else "工作站无可用实弹数据(不可达或仅合成数据),基于隔夜数据判断"}
昨日采集(对比用):{json.dumps(yday, ensure_ascii=False)[:2000] if yday else "无"}
跨资产引擎读数(确定性,判断必须引用):{json.dumps(cross, ensure_ascii=False) if cross else "无"}
昨日战绩(确定性复盘,必须引用):{json.dumps(prev, ensure_ascii=False) if prev else "无(首日或昨日无产出)"}

交易风格偏置(硬约束):交易员主做 T+0 单腿 CALL,当日了结。
- 策略默认形态 = 单腿 CALL,到期选 0DTE 或最近可用到期,必须给 t0_exit(当日平仓纪律)
- PUT 仅当看空证据明确时才提,并在 evidence 写清依据;禁止多腿组合;禁止编造权利金/报价
候选硬规则:每个候选必须锚定隔夜采集中的具体条目,逐条给出处;禁止凭训练记忆点名。
四槽股票卡制(2026-08-07 Lyra 定;candidates 必须恰好 4 条,slot 1-4 各一,
全部 单腿 CALL · T+0):
S1 主池:SP500/Nasdaq 成分股——板块必须对齐引擎 sector_leaders(20日动量主键,
   非单日涨跌),优选距 52 周高 <5% 的强势票(high52_dist_pct 读数);
   trend_regime=下降趋势 时 S1 做多降杠杆表述并写明逆势理由,或让位防守
{_s2_section(shift)}
S3 事件:8-K 重大文件(EX-2.x 并购/资产/重大合同)或 FDA approval——
   必须过流动性实测闸(liquidity_check 过闸);无够格标的宁可空槽,禁硬凑小票
{_s4_section(shift)}
每槽无合格标的 → 该槽输出 {{"slot": N, "empty": true, "empty_reason": "一句话"}};
四槽必须全部出现,禁止缺槽
排名(rank 1-4 跨四槽):趋势对齐(trend_regime/板块20日动量/52周高邻近)>
证据强度(引擎实测读数)> 时机贴近度(距入场窗)> 流动性 > 上行空间;
每卡 rank_reason 一句话引用具体读数;breadth_20d_spread<0(巨头独舞)时
广度确认缺失要在大盘 logic 里写明
时间窗硬规则:每卡 entry_window_pst / exit_window_pst 必填,给具体 PST 时段
(如 "7:15-7:45 突破确认入场" / "11:30 未达标离场,12:50 硬平仓"),禁"视情况"。
量能硬规则:入场条件里凡"放量"必须引用实测 vol_x20(≥1.5 才算放量;无读数写明"量能无实测");
隔夜/日内硬规则:index_session_split 直面 T+0 结构——日内 20 日分量为负的体制,
S1/S4 日内做多降杠杆表述并写明;隔夜分量显著为正时 S2(b) 伏击腿(唯一吃隔夜的腿)
排名可升,rank_reason 必须引用该读数;
风险预警硬规则:risk_alerts 非空必须逐条回应,写进大盘 logic 或 hedge.basis,禁无视。
对冲硬规则(hedge 段永不空白——"没信号什么都不写"被禁止):
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
{_earnings_rulebook(shift)}
{_movers_gate(shift)}- 候选所属板块应与引擎 sector_leaders 对齐;背离必须在排名理由里解释
战绩与 RSI 硬规则:
- 昨日方向错的腿,今日同逻辑再点必须写明"昨日同逻辑失误 + 今日为何不同";
  滚动命中率 <50% → 整体压低置信度表述
- RSI14 是时机过滤器不是方向信号:候选 rsi14>70 禁追高,入场条件必须写回踩确认;
  rsi14<30 禁追空 put(超卖反抽);对冲腿同规
- 禁止自估 RSI:rsi14 一律引用引擎实测(rsi14_tape/各资产读数);无读数写明"RSI 无实测",
  禁凭走势口算;引擎会给每条腿盖 tape_check 实测章与你的叙述并排对质
数字纪律(机构级;违者视为编造):
- 一切绝对数字(价位/市值/百分比)必须能在本 prompt 的采集读数中逐一找到,
  并标明来源;找不到 → 只许相对表述(昨收/盘初高点/前日低点),禁止精确小数价位
- 大盘 key_levels 同规:引擎只有日线读数、没有盘中报价——禁止给精确指数点位,
  一律相对位表述
- 概率用词("上行概率高""65%")必须带来源(polymarket 具体市场/引擎读数);无源禁用
- 市值/期权活跃度若无采集来源,liquidity 里必须写明"估计,无实测来源"

{_shift_block(shift, todays)}

只输出一个 JSON 对象——不要 markdown、不要代码围栏、不要 JSON 之外的任何文字。schema:
{{"macro": {{"sp500_bias": "看涨|看跌|中性震荡", "nasdaq_bias": "看涨|看跌|中性震荡",
  "confidence": "高|中|低", "logic": "引用 indices/收益率/VIX/赔率读数的推理",
  "key_levels": "大盘关键位——相对表述(昨收/盘初高低点),无盘中报价禁精确点位"}},
 "candidates": [{{"slot": 1, "slot_name": "主池|财报|事件|引擎位", "empty": false,
   "empty_reason": "仅 empty=true 时填",
   "rank": 1, "rank_reason": "一句话,引用引擎实测读数",
   "ticker": "", "direction": "call|put",
   "evidence": [{{"source": "edgar|fda|earnings_movers|sectors|indices|macro", "item": "条目摘要", "why": "为何构成驱动"}}],
   "key_levels": "该标的阻力/支撑及依据",
   "liquidity": "一句话:市值/期权活跃度为何扛得住 T+0",
   "strategy": {{"type": "单腿 call", "strike_logic": "行权价选择逻辑(不编报价)",
     "expiry": "0DTE|本周五|最近到期", "entry_condition": "入场触发条件",
     "entry_window_pst": "具体 PST 时段", "exit_window_pst": "具体 PST 时段+硬平仓点",
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
禁止"具体视情况而定""谨慎操作"等无效废话。全部值用中文,单值≤60字——整份 JSON 必须在输出限额内完整收尾。"""


def build_evening_prompt(raw, yday, cross=None, review=None, inventory=None):
    return f"""你是交易台参谋。当前 {fetchers.et_now_hm()} ET(收盘后;今日 AMC 财报已披露)。
写今日收盘复盘 + 明日弹药,给交易员看:
1. 今日要闻与并购/FDA/事件催化(带出处)
2. 隔夜→今日的赔率变化(Polymarket)
3. 明日日历(FDA/到期/财报/事件)
4. 明日值得盯的方向与关键位(分析,非指令)
5. 风险雷达(黑天鹅/机构拉高出货/全线下跌排查,永不留空):逐项核对——
   跨资产引擎读数(liquidation_watch、tape_flags、vix_chg_pct)、fear_greed 极值、
   hedge_assets 异动、polymarket bucket=event 赔率突变;
   财报异动榜(earnings_movers/earnings_calendar)有 |chg|≥8% 者必须点名讲清楚;
   今晚 AMC:amc_tonight 即财报"已出结果"者名单(晚班时点已全部披露)——逐个点名,
   一律用已出结果叙事(涨跌/超预期与否按 amc_results 实测讲);
   禁止出现"若超预期/待公布/今晚将出"类未出语气;
   amc_results 是实测盘后涨跌(Nasdaq 报价)——|盘后|≥8% 者必须重点讲清,
   并给明晨财报次日手册路径(gap-and-go/fade、IV 已 crush);
   amc_results 里没有读数的标的只讲事实,仍禁编数字;
   命中拉高出货 → 点名并给商品对冲方向(GLD/SLV/OXY/USO);
   命中资金迁徙(rotation_divergence 非空)→ 点名领涨海外腿(引用 rotation_leaders 数字),
   给 FXI/KWEB/EWZ/EWJ/EEM/BABA 方向,YINN 注明仅 T+0;
   命中全线下跌(liquidation_watch=true)→ 明写"商品 call 不是对冲、海外也不是避风港",
   给指数 PUT/VIXY/UUP 方向与"减仓也是对冲";未命中则明写"今日未见"
6. 晨会复盘与明日调优(复盘读数必须逐腿引用,方向命中口径=收盘对昨收):
   逐腿讲对错与原因假设;rejected_review 里 flag_misskill=true 的被否方案逐个点评
   (过滤器是否误杀,规则要不要修);给明日晨会具体调优——哪些逻辑降权、
   入场条件怎么改、RSI 时机过滤怎么用;明日/本周财报名单点名,标注 run-up 机会(run-up 仅限未来交易日;
   今日已出结果者不属 run-up);复盘读数 watch 段(amc/movers 观察名单,不计命中率)
   逐个过一遍是否需要明日跟进
数字纪律同晨会:绝对数字必须有采集来源并标明,无源用相对表述;概率词必须带来源。
源清单纪律:下方「采集源清单(权威·事实行)」是采集状态的唯一事实——禁止把 ok=true 的源
说成 SSL 失败/被墙/缺失;某源确实 ok=false 时按清单口径讲,不夸大范围。
采集源清单(权威·事实行):
{inventory or "(本班未生成清单)"}
复盘读数(确定性):{json.dumps(review, ensure_ascii=False) if review else "今日无晨会腿可复盘"}
跨资产引擎读数:{json.dumps(cross, ensure_ascii=False) if cross else "无"}
今日采集:{_slim_raw(raw)}
昨日对比:{json.dumps(yday, ensure_ascii=False)[:4000] if yday else "无"}
禁用短语:好的/综上所述/总而言之/需要注意的是/希望有帮助/如有需要——直接说事。
用 markdown,严格以 ## 分节(要闻催化/赔率变化/明日日历/明日方向/风险雷达/晨会复盘与明日调优),
每节内用短段落或列表,不要糊成整段。用中文,给数字给出处,不写废话。"""


def shadow_call(prompt):
    """D3 影子决策官(Lyra 批 2026-08-15;默认关,.env 配 SHADOW_MODEL 即开):
    同一份案卷并行出一份影子 JSON,只落盘不渲染,review 文件 -glm 后缀分账,
    与主 lane 账本互不污染;失败绝不阻塞主班,响亮记录。20 日账本判谁坐正位。"""
    model = os.getenv("SHADOW_MODEL")
    if not model:
        return None
    try:
        r = _http((os.getenv("SHADOW_BASE") or DS_BASE) + "/chat/completions",
                  {"model": model, "max_tokens": int(os.getenv("DS_MAX_TOKENS", "12000")),
                   "think": False,   # Ollama 长单不关 think 会 finish=length 空正文(8-17 同族)
                   "messages": [{"role": "user", "content": prompt}]},
                  {"Authorization": "Bearer " + (os.getenv("SHADOW_KEY")
                                                 or os.getenv("DEEPSEEK_API_KEY", "").strip() or "")})
        return r["choices"][0]["message"]["content"]
    except Exception as e:
        print("[scout] 影子 lane 失败(不阻塞主班):", str(e)[:200])
        return None


def ds_call(prompt):
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()   # 调用期读取:.env/plist 均生效(死键族收尾)
    if not key:
        raise SystemExit(
            "[scout] DEEPSEEK_API_KEY 未配置。\n"
            "  1) platform.deepseek.com 注册取 key,填 .env 或 plist\n"
            "  2) curl -s %s/models -H 'Authorization: Bearer $DEEPSEEK_API_KEY' 验模型名\n"
            "  3) 实况名与默认 %s 不符则设 DEEPSEEK_MODEL(本机 Ollama:DEEPSEEK_BASE 指 11434)"
            % (DS_BASE, DS_MODEL))
    r = _http(DS_BASE + "/chat/completions",
              {"model": DS_MODEL, "max_tokens": int(os.getenv("DS_MAX_TOKENS", "12000")),
               "think": False,   # Ollama(deepseek-v4-pro:cloud)必需;官方 OpenAI 兼容端忽略未知字段
               "messages": [{"role": "user", "content": prompt}]},
              {"Authorization": "Bearer " + key})
    return r["choices"][0]["message"]["content"]


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
    # v3.19:轮动排名以 20 日动量为主键(单日涨跌是噪声不是趋势——机构没人拿一天定轮动)
    sec.sort(key=lambda x: -(x.get("mom20_pct") if x.get("mom20_pct") is not None else x["chg_pct"]))
    def _srow(x):
        return {"name": x["name"], "chg_pct": x["chg_pct"], "mom20_pct": x.get("mom20_pct"),
                "high52_dist_pct": x.get("high52_dist_pct")}
    out["sector_leaders"] = [_srow(x) for x in sec[:3]]
    out["sector_laggards"] = [_srow(x) for x in sec[-3:]] if len(sec) >= 3 else []
    spx_m = (m.get("SP500") or {}).get("mom20_pct")
    ndq_m = (m.get("NASDAQ") or {}).get("mom20_pct")
    rsp_m = (m.get("RSP") or {}).get("mom20_pct")
    out["trend_regime"] = ("上升趋势" if (spx_m or 0) > 0 and (ndq_m or 0) > 0 else
                           "下降趋势" if (spx_m or 0) < 0 and (ndq_m or 0) < 0 else "混沌震荡") \
                          if (spx_m is not None and ndq_m is not None) else None
    # 广度差:等权 RSP 20日动量 − SP500 20日动量;>0=普涨参与广,<0=少数巨头独舞
    out["breadth_20d_spread"] = round(rsp_m - spx_m, 2) if (rsp_m is not None and spx_m is not None) else None
    out["index_mom20"] = {"SP500": spx_m, "NASDAQ": ndq_m, "RSP": rsp_m}
    # rsi14_tape:核心资产 RSI/tape 实测清单(verify 契约;DS 禁自估的引擎供数面)
    out["rsi14_tape"] = [{"name": n, "rsi14": (m.get(n) or {}).get("rsi14"),
                          "close_loc": (m.get(n) or {}).get("close_loc"),
                          "tape_flag": (m.get(n) or {}).get("tape_flag") or ""}
                         for n in ("SP500", "NASDAQ", "VIX", "GLD", "USO", "TLT")]
    # ④隔夜/日内 20 日分解(指数级)
    out["index_session_split"] = {n: {"overnight20_pct": m[n].get("on20_pct"),
                                      "intraday20_pct": m[n].get("in20_pct")}
                                  for n in ("SP500", "NASDAQ") if n in m}
    # ②相关性收敛(参数验证期:阈值 0.75 只读上卡,不接任何闸——Lyra 2026-08-07 排序令)
    def _corr(a, b):
        n = min(len(a), len(b))
        a, b = a[-n:], b[-n:]
        ma, mb = sum(a) / n, sum(b) / n
        va = sum((x - ma) ** 2 for x in a); vb = sum((x - mb) ** 2 for x in b)
        if va == 0 or vb == 0:
            return None
        return sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / ((va * vb) ** 0.5)
    rets = {n: m[n].get("_rets20") for n in risk if n in m and m[n].get("_rets20")}
    ks, pair = list(rets), []
    for i in range(len(ks)):
        for j in range(i + 1, len(ks)):
            c_ = _corr(rets[ks[i]], rets[ks[j]])
            if c_ is not None:
                pair.append(c_)
    out["risk_corr20"] = round(sum(pair) / len(pair), 2) if pair else None
    # 风险预警(确定性,alerts 非空 DS 必须逐条回应)
    alerts = []
    if out["risk_corr20"] is not None and out["risk_corr20"] > 0.75:
        alerts.append("相关性收敛 %.2f>0.75(挤兑前兆;参数验证期,只读不接闸)" % out["risk_corr20"])
    hy, lq = (m.get("HYG") or {}).get("mom20_pct"), (m.get("LQD") or {}).get("mom20_pct")
    out["credit_20d_spread"] = round(hy - lq, 2) if (hy is not None and lq is not None) else None
    if out["credit_20d_spread"] is not None and out["credit_20d_spread"] < -1.0:
        alerts.append("信用预警 HYG−LQD 20日 %+.1f%%(垃圾债跑输投级)" % out["credit_20d_spread"])
    defs = [x.get("mom20_pct") for x in sec
            if x.get("name", "").startswith(("XLP", "XLU")) and x.get("mom20_pct") is not None]
    if defs and spx_m is not None:
        dr = round(sum(defs) / len(defs) - spx_m, 2)
        out["defensive_rot_20d"] = dr
        if dr > 0:
            alerts.append("防御轮动 %+.1f%%(XLP/XLU 20日跑赢大盘)" % dr)
    vixm = (m.get("VIX") or {}).get("mom20_pct")
    if vixm is not None and vixm > 25:
        alerts.append("VIX 20日动量 %+.0f%%(波动率体制抬升)" % vixm)
    out["risk_alerts"] = alerts
    return out


def _review_files():
    b = os.path.join(OUT, "briefs")
    if not os.path.isdir(b):
        return []
    return sorted(f for f in os.listdir(b) if f.endswith("-review.json"))


def build_review(date, suffix=""):
    """确定性复盘(晚班 21:00 跑,拿全日K线):读当日晨会 json,逐腿取收盘涨跌/
    close_loc/RSI14,判方向命中。口径如实:收盘对昨收判定,非盘中入场路径复现。"""
    # v3.25:三班合并复盘——当日 morning/midday/earnings 各班在案腿全部进复盘,
    # 腿按 (ticker,direction) 去重取首见;影子 lane(suffix)仅晨班,口径不变。
    shifts = ("morning", "midday", "earnings") if not suffix else ("morning",)
    docs = []
    for sh in shifts:
        p = os.path.join(OUT, "briefs", "%s-%s%s.json" % (date, sh, suffix))
        if os.path.exists(p):
            try:
                docs.append((sh, json.load(open(p, encoding="utf-8"))))
            except Exception:
                pass
    if not docs:
        return None
    # v3.16 合流:watch 名单(amc_tonight/movers/bmo)结构性进复盘——TEAM 零复盘痕迹的根修;
    # 仅观察,不计命中率
    wset = set()
    legs = []
    seen = set()
    rejected_all = []
    for sh, doc in docs:
        ds = doc.get("ds") or doc
        eng = doc.get("_engine") or {}
        for k in ("amc_tonight", "earnings_movers", "bmo_tomorrow"):
            wset |= {((x.get("symbol") if isinstance(x, dict) else x) or "").upper()
                     for x in (eng.get(k) or [])}
        for l in (ds.get("candidates") or []):
            key = ("c", (l.get("ticker") or "").upper(), (l.get("direction") or "call").lower())
            if key in seen:
                continue
            seen.add(key)
            legs.append(dict(l, _src="candidate", _shift=sh))
        for l in ((ds.get("hedge") or {}).get("legs") or []):
            key = ("h", (l.get("ticker") or "").upper(), (l.get("direction") or "call").lower())
            if key in seen:
                continue
            seen.add(key)
            legs.append(dict(l, _src="hedge", _shift=sh))
        rejected_all += (ds.get("rejected") or [])
    watch = sorted(w for w in wset if re.fullmatch(r"[A-Z]{1,5}", w))
    out = []
    for l in legs:
        t = (l.get("ticker") or "").upper()
        if l.get("empty") or not t:
            continue          # 空槽卡合法,静默跳过
        if not re.fullmatch(r"[A-Z]{1,5}", t):
            print("[scout] 复盘跳过非常规代码:", t)
            continue
        d = fetchers._stooq_daily(t.lower() + ".us", t, "review")
        if not d:
            continue
        direction = (l.get("direction") or "call").lower()
        chg = d.get("chg_pct") or 0
        out.append({"ticker": t, "direction": direction, "src": l.get("_src", "candidate"),
                    "shift": l.get("_shift", "morning"),
                    "chg_pct": d.get("chg_pct"),
                    "close_loc": d.get("close_loc"), "rsi14": d.get("rsi14"),
                    "hit": chg > 0 if direction == "call" else chg < 0})
    rej_out = []
    rej_seen = set()
    for r0 in rejected_all:
        if (r0.get("ticker") or "").upper() in rej_seen:
            continue
        rej_seen.add((r0.get("ticker") or "").upper())
        t = (r0.get("ticker") or "").upper()
        if not re.fullmatch(r"[A-Z]{1,5}", t or ""):
            continue
        d0 = fetchers._stooq_daily(t.lower() + ".us", t, "review_rejected")
        if d0:
            chg0 = d0.get("chg_pct")
            rej_out.append({"ticker": t, "chg_pct": chg0, "reason": r0.get("reason"),
                            "flag_misskill": (chg0 or 0) > 2.0})   # 被否却涨>2% = 疑误杀,晚报必点评
    if not out:
        return None
    cand = [x for x in out if x.get("src", "candidate") == "candidate"]
    nh = sum(1 for x in cand if x["hit"])
    rev = {"date": date, "legs": out, "rejected_review": rej_out,
           "watch": watch,
           "hit": "%d/%d" % (nh, len(cand)) if cand else "0/0",
           "hit_rate": round(nh / len(cand), 2) if cand else None,
           "basis": "收盘对昨收判定方向命中(仅候选腿计入;对冲腿分账;watch 段仅观察不计命中率);非盘中入场路径复现"}
    os.makedirs(os.path.join(OUT, "briefs"), exist_ok=True)
    with open(os.path.join(OUT, "briefs", "%s-review%s.json" % (date, suffix)), "w", encoding="utf-8") as f:
        json.dump(rev, f, ensure_ascii=False, indent=1)
    return rev


def load_prev_review(today):
    # v3.22 同族第二处:rolling 已滤周末,此处不滤则周一"昨日战绩"仍会拿周六遗留假账
    files = [f for f in _review_files() if f[:10] < today
             and datetime.date.fromisoformat(f[:10]).weekday() < 5]
    if not files:
        return None
    return json.load(open(os.path.join(OUT, "briefs", files[-1]), encoding="utf-8"))


def rolling_summary(upto_incl):
    # v3.22:滚动剔除周末日期文件(历史遗留假腿自动失效),且只统计候选腿
    files = [f for f in _review_files() if f[:10] <= upto_incl
             and datetime.date.fromisoformat(f[:10]).weekday() < 5][-5:]
    tot = hit = 0
    for fn in files:
        r = json.load(open(os.path.join(OUT, "briefs", fn), encoding="utf-8"))
        for l in r.get("legs") or []:
            if l.get("src", "candidate") != "candidate":
                continue
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
    # 30 次 stooq 取数是上限兜底,榜单仍只出前 8
    for sym, tag in syms[:30]:
        r = fetchers._stooq_daily(sym.lower() + ".us", sym, "earnings_movers")
        if r and r.get("chg_pct") is not None:
            out.append({"symbol": sym, "when": tag, "chg_pct": r["chg_pct"],
                        "vol_x20": r.get("vol_x20"),
                        "close_loc": r.get("close_loc"), "rsi14": r.get("rsi14")})
    out.sort(key=lambda x: -abs(x["chg_pct"]))
    return out[:8]


def amc_tonight(payload, today):
    """确定性名单:今日 AMC(今晚盘后出财报)——晨会时财报未出,不进 movers 硬闸;
    显式喂 DS 供手册第二步(run-up)评估,并上引擎卡。日历本身按市值排序,取前10。"""
    out = []
    for src in payload.get("results", payload.get("sources", [])):
        if src.get("source") == "earnings_calendar":
            for it in src.get("items", []):
                sym = (it.get("symbol") or "").upper()
                if it.get("date") == today and "after" in (it.get("when") or "") \
                        and re.fullmatch(r"[A-Z]{1,5}", sym):
                    out.append(sym)
    # "已出结果者"的判定 = 名单本身(21:00 PST 跑晚班时今日 AMC 基本已全部披露)。
    # 禁止从数据里"侦测谁出了结果"——stooq 没有那个信号,任何侦测都是编。
    # 以后的窗口不要在这里加机制(隔壁 Fable 定,守恒盖章)。
    # v3.16.2 合流:cap 15→30——TEAM 型中盘曾被裁在名单口上(verify 契约)
    out = out[:30]
    # v3.18:逐票附实测读数(rsi14/5日累计涨幅)——S2(b) 尾盘伏击与双杀排除的数据基
    rich = []
    for sym in out:
        r = fetchers._stooq_daily(sym.lower() + ".us", sym, "amc_tonight")
        rich.append({"symbol": sym, "rsi14": (r or {}).get("rsi14"),
                     "chg5_pct": (r or {}).get("chg5_pct"), "chg_pct": (r or {}).get("chg_pct")})
    return rich


def _next_trading_day(today):
    d = datetime.date.fromisoformat(today) + datetime.timedelta(days=1)
    while d.weekday() >= 5:
        d += datetime.timedelta(days=1)
    return d.isoformat()


def bmo_tomorrow(payload, today):
    """确定性名单:明日 BMO(明晨盘前出财报)——v3.25 新腿名单源(Lyra 拍板 2026-08-19,
    EL 案根治:吃 BMO 票只能前一日尾盘买入持过夜)。when 实值按 V6 取证:
    time-pre-market / time-after-hours / time-not-supplied——匹配 pre-market,不猜别名。
    日历本身按市值排序,cap 30,逐票附实测读数(双杀排除的数据基)。"""
    nd = _next_trading_day(today)
    out = []
    for src_ in payload.get("results", payload.get("sources", [])):
        if src_.get("source") == "earnings_calendar":
            for it in src_.get("items", []):
                sym = (it.get("symbol") or "").upper()
                if it.get("date") == nd and "pre-market" in (it.get("when") or "") \
                        and re.fullmatch(r"[A-Z]{1,5}", sym):
                    out.append(sym)
    out = list(dict.fromkeys(out))[:30]
    rich = []
    for sym in out:
        r = fetchers._stooq_daily(sym.lower() + ".us", sym, "bmo_tomorrow")
        rich.append({"symbol": sym, "rsi14": (r or {}).get("rsi14"),
                     "chg5_pct": (r or {}).get("chg5_pct"), "chg_pct": (r or {}).get("chg_pct")})
    return rich


def upcoming_earnings(payload, today):
    """确定性名单:未来 2-8 个交易日财报(run-up 窗)——S2a 腿的引擎供数。
    EL 案根修第二半:EL 08-15 起就在日历(V2 取证),但该腿此前只有 prompt 规则、
    没有引擎名单,数百行原始日历被 _slim_raw 预算裁剪,DS 结构性看不见。
    市值降序 cap 12,前 8 附实测读数(控 FMP 调用)。"""
    d = datetime.date.fromisoformat(today)
    win = set()
    step = d
    for _ in range(8):
        step = datetime.date.fromisoformat(_next_trading_day(step.isoformat()))
        win.add(step.isoformat())
    win.discard(_next_trading_day(today))          # 次一日归 BMO/AMC 腿,run-up 窗从第 2 个交易日起
    rows = []
    for src_ in payload.get("results", payload.get("sources", [])):
        if src_.get("source") == "earnings_calendar":
            for it in src_.get("items", []):
                sym = (it.get("symbol") or "").upper()
                if it.get("date") in win and re.fullmatch(r"[A-Z]{1,5}", sym):
                    mc = fetchers._parse_money(it.get("marketCap")) or 0
                    rows.append({"symbol": sym, "date": it.get("date"),
                                 "when": it.get("when"), "_mc": mc})
    rows.sort(key=lambda x: -x["_mc"])
    seen, out = set(), []
    for x in rows:
        if x["symbol"] in seen:
            continue
        seen.add(x["symbol"])
        out.append({k: v for k, v in x.items() if k != "_mc"})
        if len(out) >= 12:
            break
    for x in out[:8]:
        r = fetchers._stooq_daily(x["symbol"].lower() + ".us", x["symbol"], "upcoming_earnings")
        x.update({"rsi14": (r or {}).get("rsi14"), "chg5_pct": (r or {}).get("chg5_pct")})
    return out


def build_handover(today, prev):
    """昨夜交班块(v3.25 F1):过夜伏击腿 + 昨日 watch 的盘初实测。
    过夜腿识别 = 昨日各班 brief 候选里 earnings_note/note 含"持过财报"且非空槽。
    V1/复盘案根修:唯一合法过夜例外此前没有次日强制跟踪义务,ZTO 持过财报次日无人交班。"""
    legs, watch = [], []
    try:
        bdir = os.path.join(OUT, "briefs")
        files = [f for f in os.listdir(bdir)
                 if re.match(r"\d{4}-\d{2}-\d{2}-(morning|midday|earnings)\.json$", f)] if os.path.isdir(bdir) else []
        prev_days = sorted({f[:10] for f in files if f[:10] < today})
        pd = prev_days[-1] if prev_days else None
        if pd:
            for sh in ("morning", "midday", "earnings"):
                p = os.path.join(bdir, "%s-%s.json" % (pd, sh))
                if not os.path.exists(p):
                    continue
                try:
                    ds = (json.load(open(p, encoding="utf-8")) or {}).get("ds") or {}
                except Exception:
                    continue
                for c in (ds.get("candidates") or []):
                    st = c.get("strategy") or {}
                    note = "%s %s" % (st.get("earnings_note") or c.get("earnings_note") or "",
                                      c.get("note") or "")
                    t = str(c.get("ticker") or "").upper()
                    if t and not c.get("empty") and "持过财报" in note and re.fullmatch(r"[A-Z]{1,5}", t):
                        legs.append({"ticker": t, "from": "%s %s" % (pd, sh)})
    except Exception as e:
        print("[scout] 交班块构建异常(不阻塞):", e)
    if prev:
        watch = [w for w in (prev.get("watch") or []) if re.fullmatch(r"[A-Z]{1,5}", str(w))][:15]
    syms = sorted({l["ticker"] for l in legs} | set(watch))[:18]
    snaps = fetchers.quote_layer.snapshot(syms) if syms else {}

    def row(t):
        d = snaps.get(t) or {}
        return {"symbol": t, "chg_pct": d.get("chg_pct"), "rsi14": d.get("rsi14"),
                "close_loc": d.get("close_loc")}
    return {"overnight_legs": [dict(l, **row(l["ticker"])) for l in legs],
            "watch_tape": [row(t) for t in watch],
            "rule": "过夜腿必须首屏处置(gap-and-go 续持/开盘即走);watch 显著变化必须点名"}


def load_today_shifts(today, before):
    """当日已出班次的在案腿摘要——供盘中/财报班复核(v3.25)。"""
    order = ["morning", "midday", "earnings"]
    out = {}
    for sh in order[:order.index(before)] if before in order else []:
        p = os.path.join(OUT, "briefs", "%s-%s.json" % (today, sh))
        if not os.path.exists(p):
            continue
        try:
            ds = (json.load(open(p, encoding="utf-8")) or {}).get("ds") or {}
        except Exception:
            continue
        out[sh] = {"candidates": [{"ticker": c.get("ticker"), "slot": c.get("slot"),
                                   "direction": c.get("direction"), "empty": bool(c.get("empty"))}
                                  for c in (ds.get("candidates") or [])],
                   "conclusion": ds.get("conclusion")}
    return out


def persist_skips(raw_path, payload):
    """引擎期 skips 回写 raw(v3.25;V1 案根修):采集期落盘后,afterhours/tape_check/
    movers 等引擎期取数的 skips 只存在内存——ZTO 盘后缺数曾无迹可查。"""
    try:
        payload["skips"] = fetchers.SKIPS
        json.dump(payload, open(raw_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception as e:
        print("[scout] skips 回写失败(不阻塞):", e)


def apply_liquidity_gate(data):
    """确定性流动性闸(爬虫#11):候选+对冲腿逐个实测市值/日均量,盖 liquidity_check 章。
    引擎只盖章不删卡——未过闸红标,买不买拍板在 Lyra(主频原则)。
    地板 env LIQ_MCAP_FLOOR_B,默认 $2.0B。"""
    legs = list(data.get("candidates") or []) + list((data.get("hedge") or {}).get("legs") or [])
    syms = sorted({(l.get("ticker") or "").upper() for l in legs
                   if re.fullmatch(r"[A-Z]{1,5}", (l.get("ticker") or "").upper())})
    if not syms:
        return data
    res = fetchers.fetch_ticker_liquidity(syms)
    m = {i["symbol"]: i for i in (res.get("items") or [])}
    floor = fetchers.LIQ_MCAP_FLOOR_B
    for l in legs:
        i = m.get((l.get("ticker") or "").upper())
        if not i:
            l["liquidity_check"] = {"mcap_b": None, "floor_b": floor,
                                    "verdict": "无实测——DS 的 liquidity 按估计对待"}
        else:
            ok = i["mcap_b"] is not None and i["mcap_b"] >= floor
            l["liquidity_check"] = {"mcap_b": i["mcap_b"], "avg_vol": i.get("avg_vol"), "floor_b": floor,
                                    "verdict": "过闸" if ok else ("未过闸(<$%.1fB)——谨慎,拍板在 Lyra" % floor)}
    return data


def apply_tape_check(data):
    """v3.16.2 合流:引擎给每条候选/对冲腿盖 tape_check 实测章(rsi14/close_loc/
    tape_flag/chg),与 DS 叙述并排对质——RSI 禁自估的引擎侧牙。只盖章不删卡,拍板在 Lyra。
    读数走 quote_layer 缓存,候选票多已在 movers/amc 预热,近零增量调用。"""
    legs = list(data.get("candidates") or []) + list((data.get("hedge") or {}).get("legs") or [])
    for l in legs:
        t = (l.get("ticker") or "").upper()
        if l.get("empty") or not re.fullmatch(r"[A-Z]{1,5}", t or ""):
            continue
        d = fetchers._stooq_daily(t.lower() + ".us", t, "tape_check")
        l["tape_check"] = ({"rsi14": d.get("rsi14"), "close_loc": d.get("close_loc"),
                            "tape_flag": d.get("tape_flag") or "", "chg_pct": d.get("chg_pct")}
                           if d else {"verdict": "无实测(FMP/Theta/Alpaca 三源 miss)"})
    return data


def emit_aether_scout(day, mode, title, data, cross, body_text=""):
    """AETHER 事件流 emit(verify 契约:morning/evening 主路径各一次)。payload 形状
    对齐 scout_land_option.emit(source=aether · kind=aether_scout_brief)。
    gateway(:8501)不可达 = 响亮记录不阻塞——emit 是账本镜像,不是班次前置。"""
    payload = {"date": day, "mode": mode, "title": title,
               "body": (body_text or "")[:2000],
               "brief_path": os.path.join(OUT, "briefs", "%s-%s.html" % (day, mode)),
               "via": "scout_agent",
               "structured": ({"_engine": cross, "ds": data} if data is not None else None),
               "liquidation_watch": bool((cross or {}).get("liquidation_watch")),
               "amc_tonight": (cross or {}).get("amc_tonight")}
    blob = json.dumps({"source": "aether", "kind": "aether_scout_brief",
                       "payload": payload}, ensure_ascii=False).encode()
    try:
        req = urllib.request.Request(GW + "/store/events", data=blob,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=15, context=fetchers._ssl_context()) as r:
            print("[scout] aether emit", r.status, "(%s)" % mode)
    except Exception as e:
        print("[scout] aether emit 失败(不阻塞):", str(e)[:160])


def source_inventory(payload):
    """采集源清单(权威·事实行)——逐源 ok=true/false + 条数 + 错因。
    晚报叙事关于采集状态的最高权威是本清单(v3.16.4 契约):DS 不得伪称 SSL/缺失。"""
    rows = []
    for src_ in payload.get("results", payload.get("sources", [])) or []:
        flag = "ok=true" if src_.get("ok") else "ok=false"
        err = "" if src_.get("ok") else (" · " + str(src_.get("error") or "")[:80])
        rows.append("%s %s n=%d%s" % (src_.get("source"), flag, len(src_.get("items") or []), err))
    return "\n".join(rows)


_CLAIM_FAIL_RX = r"(失败|被墙|不可用|抓取不到|无法访问|超时|SSL|证书|中断|全灭|未采集|拿不到|断连)"


def lint_evening_source_claims(text, payload):
    """确定性 lint(v3.16.4):晚报叙事把 ok=true 的源说成失败/SSL——以清单为准就地重写
    并记账。只纠源状态谎言,永不碰数字/引用/风险提示(与 Grid 降噪同规)。"""
    fixes = []
    ok_sources = [str(s.get("source")) for s in
                  (payload.get("results", payload.get("sources", [])) or []) if s.get("ok")]
    for name in ok_sources:
        rx = re.compile(r"^.*%s.*%s.*$" % (re.escape(name), _CLAIM_FAIL_RX), re.M)
        text, n = rx.subn("(叙述与采集清单冲突,已按事实行纠正:%s ok=true)" % name, text)
        if n:
            fixes.append("%s×%d" % (name, n))
    if fixes:
        text += ("\n\n---\n[源清单 lint:纠正伪称失败 %s;事实行(最高权威)=采集源清单,"
                 "见 prompt 附录]" % ",".join(fixes))
    return text


def evening_ds_with_lint(prompt, payload):
    """晚班出稿链:DS → Grid 降噪 → 源清单 lint。事实行(最高权威)后置硬闸——
    prompt 纪律是软约束,这里是牙。"""
    return lint_evening_source_claims(denoise(ds_call(prompt)), payload)


def expanded_evening_review(date, final_md):
    """晚报 EXPANDED-GLM review(v3.16.5 契约:8501 · scout-review-日 · glm52_cloud)。
    路由/字段取自现场 verify 契约;gateway 不可达或空回 = 响亮记录不阻塞晚班。"""
    scout_expanded_memory_node = "scout-review-%s" % date
    body = {"lane": "scout_evening",
            "cloud_backend": "glm52_cloud",
            "memory_node": scout_expanded_memory_node,
            "persist": True,
            "task": (final_md or "")[:9000],
            "messages": [
                {"role": "system", "content": "Scout 晚报 EXPANDED review。中文 Markdown,不编报价。"},
                {"role": "user", "content": (final_md or "")[:9000]},
            ]}
    try:
        blob = json.dumps(body, ensure_ascii=False).encode()
        req = urllib.request.Request(WB + "/gateway/task/expanded", data=blob,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=300, context=fetchers._ssl_context()) as r:
            res = json.loads(r.read().decode())
        txt = (res.get("final") or res.get("content") or "").strip()
        if txt:
            p = os.path.join(OUT, "briefs", "%s-evening-glm-review.md" % date)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w", encoding="utf-8").write(txt)
            print("[scout] EXPANDED-GLM review 落盘:", p)
            sys_content = "Scout 晚报 EXPANDED review。中文 Markdown,不编报价。"
            store_msgs = [
                {"role": "user", "content": sys_content + "\n\n" + (final_md or "")[:9000], "surface": "grid-app"},
                {"role": "assistant", "content": txt, "surface": "grid-app"},
            ]
            try:
                sreq = urllib.request.Request(
                    GW + "/store/conversations/" + scout_expanded_memory_node + "/messages",
                    data=json.dumps(store_msgs, ensure_ascii=False).encode(),
                    headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(sreq, timeout=30, context=fetchers._ssl_context()) as sr:
                    sr.read()
                print("[scout] EXPANDED-GLM review 已同步 store node:", scout_expanded_memory_node)
            except Exception as se:
                print("[scout] EXPANDED-GLM review store 同步失败(不阻塞):", str(se)[:120])
        else:
            print("[scout] EXPANDED-GLM review 空回(响亮记录,不阻塞)")
        return txt or None
    except Exception as e:
        print("[scout] EXPANDED-GLM review 失败(不阻塞):", str(e)[:160])
        return None


# ———— Grid 纪律降噪层(2026-08-08,Grid 入互审网后首个采纳建议)————
# 只删已知废话模式,永不碰数字/引用/风险提示;删了在文末响亮记账,不静默。
_NOISE_RX = [
    re.compile(r"^(好的|明白了|当然)[,,]?[^\n]{0,24}(如下|分析)[::]?\s*$", re.M),
    re.compile(r"^(总的来说|总而言之|综上所述|整体而言|需要注意的是|值得一提的是|值得注意的是)[,,::]\s*", re.M),
    re.compile(r"希望(以上|这些)?(内容|分析|信息)?(对你|对您)?有(所)?帮助[。!!]?"),
    re.compile(r"如(有|果)(其他)?(需要|问题|疑问)[^。\n]{0,20}[。!!]?"),
    re.compile(r"^(首先|其次|最后)[,,]我们(来|再)?(看|分析)一?下?[::]?\s*", re.M),
]


def denoise(text):
    """晚报降噪:确定性删废话短语,合并多余空行;命中即记账入文末。"""
    n0, hits = len(text or ""), 0
    for rx in _NOISE_RX:
        text, k = rx.subn("", text)
        hits += k
    text = re.sub(r"\n{3,}", "\n\n", text)
    if hits:
        text += "\n\n---\n[Grid 纪律降噪:删 %d 处废话,%d→%d 字]" % (hits, n0, len(text))
    return text


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
        for e in (c.get("evidence") or [])) or '<div class="ev">(无证据条目——按硬规则本卡不应存在)</div>'
    lc = c.get("liquidity_check") or {}
    lc_txt = (("$%.2fB · %s" % (lc["mcap_b"], lc.get("verdict", ""))) if lc.get("mcap_b") is not None
              else lc.get("verdict"))
    tc = c.get("tape_check") or {}
    tc_txt = (tc.get("verdict") if "verdict" in tc else
              ("RSI %s · loc %s · 日%s%%%s" % (tc.get("rsi14"), tc.get("close_loc"),
               tc.get("chg_pct"), (" · " + tc["tape_flag"]) if tc.get("tape_flag") else ""))
              if tc else None)
    rows = [("排名理由", c.get("rank_reason")),
            ("形态", st.get("type")), ("行权价逻辑", st.get("strike_logic")),
            ("到期", st.get("expiry")), ("入场条件", st.get("entry_condition")),
            ("入场窗(PST)", st.get("entry_window_pst")), ("出场窗(PST)", st.get("exit_window_pst")),
            ("止损", st.get("stop")), ("作废条件", st.get("abandon")),
            ("财报", st.get("earnings_note")), ("流动性(DS)", c.get("liquidity")),
            ("流动性实测(引擎)", lc_txt),
            ("RSI/tape 实测(引擎)", tc_txt),
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
        SLOTS = {1: "主池", 2: "财报", 3: "8-K/FDA", 4: "引擎位"}
        cs = sorted(cands, key=lambda c: (c.get("rank") or 9, c.get("slot") or 9))
        cells = []
        for c in cs:
            sl, sn = c.get("slot"), (c.get("slot_name") or SLOTS.get(c.get("slot"), ""))
            if c.get("empty"):
                cells.append('<div class="empty">S%s %s · 今日空槽'
                             '<br><span style="font-size:var(--f1)">%s</span></div>'
                             % (_esc(sl), _esc(sn), _esc(c.get("empty_reason", ""))))
            else:
                cells.append(_cand_card(c, date, "S%s·RANK %s" % (sl or "?", c.get("rank") or "?")))
        out.append('<section><h2>二 · 四槽股票卡(全部 单腿 CALL · T+0)</h2>%s</section>' % "".join(cells))
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
    movers = " · ".join("%s %+.1f%%(%s%s)" % (x["symbol"], x["chg_pct"], x["when"],
                         (",量%.1fx" % x["vol_x20"]) if x.get("vol_x20") else "")
                         for x in (cross.get("earnings_movers") or [])[:4]) or None
    if movers:
        rows.append(("财报异动(昨AMC/今BMO)", movers))
    if cross.get("amc_tonight"):
        def _amcfmt(x):
            if isinstance(x, str):
                return x
            hot = (x.get("chg5_pct") or 0) > 15 or (x.get("rsi14") or 0) > 75
            return x.get("symbol", "?") + ("⚠" if hot else "")
        rows.append(("今晚财报(AMC watch,⚠=双杀禁入)",
                     " · ".join(_amcfmt(x) for x in cross["amc_tonight"][:6])))
    if cross.get("bmo_tomorrow"):
        def _bmofmt(x):
            hot = (x.get("chg5_pct") or 0) > 15 or (x.get("rsi14") or 0) > 75
            return x.get("symbol", "?") + ("⚠" if hot else "")
        rows.append(("明日财报(BMO 伏击名单,⚠=双杀禁入)",
                     " · ".join(_bmofmt(x) for x in cross["bmo_tomorrow"][:6])))
    if cross.get("upcoming_earnings"):
        rows.append(("未来 2-8 日财报(run-up 窗)", " · ".join(
            "%s(%s)" % (x["symbol"], (x.get("date") or "")[5:]) for x in cross["upcoming_earnings"][:8])))
    ho = cross.get("handover") or {}
    if ho.get("overnight_legs"):
        rows.append(("昨夜过夜腿(必须首屏处置)", " · ".join(
            "%s %s" % (x["symbol"], ("%+.2f%%" % x["chg_pct"]) if x.get("chg_pct") is not None else "无读数")
            for x in ho["overnight_legs"])))
    if ho.get("watch_tape"):
        rows.append(("昨日 watch 盘初", " · ".join(
            "%s %s" % (x["symbol"], ("%+.1f%%" % x["chg_pct"]) if x.get("chg_pct") is not None else "—")
            for x in ho["watch_tape"][:10])))
    if cross.get("amc_results"):
        rows.append(("盘后异动(实测)", " · ".join(
            "%s %+.1f%%" % (x["symbol"], x["ah_chg_pct"]) for x in cross["amc_results"][:5])))
    if cross.get("trend_regime"):
        rows.append(("趋势体制(20日)", "%s · 广度差 %s%%(等权−市值权;负=巨头独舞)"
                     % (cross["trend_regime"], cross.get("breadth_20d_spread", "—"))))
    ssp = cross.get("index_session_split") or {}
    if ssp:
        rows.append(("隔夜/日内(20日)", " · ".join(
            "%s 隔夜%+.1f%%/日内%+.1f%%" % (n, v.get("overnight20_pct") or 0, v.get("intraday20_pct") or 0)
            for n, v in ssp.items())))
    if cross.get("risk_alerts") is not None:
        base = "corr %s · 信用 %s%%" % (cross.get("risk_corr20", "—"), cross.get("credit_20d_spread", "—"))
        rows.append(("风险预警", ("; ".join(cross["risk_alerts"]) + "(" + base + ")")
                     if cross["risk_alerts"] else "无(" + base + ")"))
    sl = cross.get("sector_leaders") or []
    sg = cross.get("sector_laggards") or []
    if sl:
        def _sfmt(x):
            m20 = x.get("mom20_pct")
            return "%s %s(日%+.1f%%)" % (x["name"], ("%+.1f%%/20d" % m20) if m20 is not None else "—", x["chg_pct"])
        rows.append(("板块轮动(20日动量主键)", "领:%s · 尾:%s"
                     % (" ".join(_sfmt(x) for x in sl), " ".join(_sfmt(x) for x in sg))))
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
    body = warn + _engine_card(cross) + (_render_structured(date, data) if data else _md_fallback(raw_text))
    return ('<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"/>'
            '<meta name="viewport" content="width=device-width,initial-scale=1"/>'
            '<title>SCOUT · %s · %s</title><style>%s</style></head><body>'
            '<header><h1>SCOUT</h1><span class="sub">%s · %s · 数据as-of %s · 参谋作业,Lyra 拍板</span></header>'
            '%s<footer>build scout v3.25 · 三班制+BMO伏击+FMP路由(v3.24 合流线) · FMP主源+Theta+Alpaca backup · emit/tape_check/rsi14_tape/源清单lint/EXPANDED-GLM · 影子lane · 账本卫生 · Grid降噪 · 四槽卡 · ET锚定 · '
            '渲染:_render_structured/_cand_card/_md_fallback</footer></body></html>'
            % (mode.upper(), _esc(date), BRIEF_CSS, mode, _esc(date),
               {"morning": "盘初 ~9:45 ET(当日行为部分K线)",
                "midday": "盘中 ~13:40 ET(当日行为盘中K线)",
                "earnings": "尾盘 ~15:35 ET(近全日K线)"}.get(mode, "收盘(全日K线)"), body))


def render_console(title, body, date, mode, data=None, cross=None):
    """DS 作业进 console 落档(work_log 入魂器);console 不可达则本地落盘。"""
    payload_doc = ("[DS 决策官作业·JSON(GLM review/编译直接吃)] "
                   + json.dumps(data, ensure_ascii=False)[:8000]) if data else \
                  ("[DS 决策官作业,存档] " + body[:8000])
    try:
        ck = os.getenv("CONSOLE_KEY", "").strip()   # 调用期读取(死键族收尾)
        if not ck:
            raise RuntimeError("CONSOLE_KEY 未配置")
        t = _http(CONSOLE + "/api/tasks",
                  {"workspace": "trade", "title": title, "owner_node": "deepseek_lane",
                   "risk_level": "read", "io_contract": payload_doc},
                  {"X-Console-Key": ck})
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
    ap.add_argument("--mode", choices=["evening", "morning", "midday", "earnings"], default="evening")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-fetch", action="store_true")
    ap.add_argument("--review", choices=["expanded", "off"], default="expanded",
                    help="晚班 EXPANDED-GLM review(v3.16.5;8501 不可达自动跳过)")
    a = ap.parse_args()
    # .env 已在模块顶加载(先于 import fetchers 与常量——死键族根治,勿移回此处)
    today = fetchers.trading_date().isoformat()   # v3.12:ET 锚定,机器时区无关
    # v3.22 账本卫生:周末不出班——launchd 七天都跑,周六日 stooq 返回的是周五K线,
    # 曾造成同一根K线三记入账(JPM/FCX 案例,命中率虚高 67.9%→去重 62.5%)
    if datetime.date.fromisoformat(today).weekday() >= 5:
        print("[scout] %s 非交易日——不出班不写复盘(账本卫生;节假日仍为已知边界)" % today)
        return
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
    if a.mode in ("morning", "midday", "earnings"):
        shift = a.mode
        if shift == "earnings":
            # 财报班(开卷):四件套全上——movers 硬闸 / 今晚 AMC / 明日 BMO / 2-8 日 run-up
            cross["earnings_movers"] = earnings_movers(payload, today)
            cross["amc_tonight"] = amc_tonight(payload, today)
            cross["bmo_tomorrow"] = bmo_tomorrow(payload, today)
            cross["upcoming_earnings"] = upcoming_earnings(payload, today)
        elif shift == "midday":
            cross["amc_tonight"] = amc_tonight(payload, today)   # 初筛名单(观察,不建仓)
        # morning 班不算财报榜——本班不出财报腿(Lyra 2026-08-19 拍板)
        prev = load_prev_review(today)
        if prev:
            prev["rolling"] = rolling_summary(prev["date"])
            cross["prev_review"] = {k: prev.get(k) for k in
                                    ("date", "hit", "rolling", "watch", "rejected_review")
                                    if prev.get(k) is not None}
        if shift == "morning":
            cross["handover"] = build_handover(today, prev)
        todays = load_today_shifts(today, shift)
        title = "Scout %s · %s" % (_SHIFT_TITLE[shift], today)
        ws = fetch_workstation_state()
        prompt = build_trading_prompt(payload, ws, yday, cross, prev, shift=shift, todays=todays)
        body = ds_call(prompt)
        data = _extract_json(body) if (body or "").strip() else None
        if data is None:
            hint = ("DS 空正文(finish=length/未关 think 类,8-17 案)" if not (body or "").strip()
                    else "疑输出截断,查 DS_MAX_TOKENS" if body.lstrip().startswith("{")
                    else "DS 未按 schema")
            print("[scout] 晨会单 JSON 解析失败(%s)——降级文本渲染,json 落失败标记(land 拒吃口)" % hint)
            os.makedirs(os.path.join(OUT, "briefs"), exist_ok=True)
            with open(os.path.join(OUT, "briefs", "%s-%s.json" % (today, shift)), "w", encoding="utf-8") as f:
                json.dump({"_engine": cross, "ds": {"_parse_failed": True, "hint": hint}},
                          f, ensure_ascii=False, indent=1)
        else:
            data = apply_liquidity_gate(data)
            data = apply_tape_check(data)
        render_console(title, body, today, shift, data, cross)
        emit_aether_scout(today, shift, title, data, cross, body)
        persist_skips(raw_path, payload)
        sbody = shadow_call(prompt) if shift == "morning" else None
        if sbody is not None:
            sdata = _extract_json(sbody)
            with open(os.path.join(OUT, "briefs", "%s-morning-glm.json" % today), "w", encoding="utf-8") as f:
                json.dump({"_engine": cross, "ds": sdata if sdata is not None else {"_parse_failed": True}},
                          f, ensure_ascii=False, indent=1)
            print("[scout] 影子 lane 落盘:%s-morning-glm.json(%s)"
                  % (today, "JSON ok" if sdata is not None else "解析失败已标记"))
    else:
        # 雷达第5项供数:晚报 prompt 一直令 DS 核对 earnings_movers,旧版 evening 从未计算(对空气核对)
        cross["earnings_movers"] = earnings_movers(payload, today)
        cross["amc_tonight"] = amc_tonight(payload, today)
        if cross["amc_tonight"]:
            ah = fetchers.fetch_afterhours([x["symbol"] if isinstance(x, dict) else x
                                            for x in cross["amc_tonight"]])
            cross["amc_results"] = sorted(
                [i for i in (ah.get("items") or []) if i.get("ah_chg_pct") is not None],
                key=lambda x: -abs(x["ah_chg_pct"]))
        rev = build_review(today)
        build_review(today, "-glm")   # 影子 lane 分账复盘(无影子文件则静默跳过)
        if rev:
            rev["rolling"] = rolling_summary(today)
            cross["today_review"] = {"date": today, "hit": rev["hit"], "rolling": rev["rolling"]}
        inv = source_inventory(payload)
        prompt = build_evening_prompt(payload, yday, cross, rev, inv)
        body = evening_ds_with_lint(prompt, payload)
        render_console("Scout 晚报复盘 · " + today, body, today, "evening", None, cross)
        if a.review == "expanded":
            expanded_evening_review(today, body)
        emit_aether_scout(today, "evening", "Scout 晚报复盘 · " + today, None, cross, body)
        persist_skips(raw_path, payload)


if __name__ == "__main__":
    main()
