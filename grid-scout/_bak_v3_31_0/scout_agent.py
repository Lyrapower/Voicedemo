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
import argparse, datetime, html, json, os, re, subprocess, sys, urllib.error, urllib.request


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
import factors
import attribution

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
        return ("S2 AMC 初筛卡(v3.25.6,Lyra 拍板 2026-08-20:S2 不再占位空槽):\n"
                "   amc_tonight 名单非空时本槽必须出实质卡(empty=false)——内容=名单前三点名\n"
                "   (按 earn_score 序)+逐票双杀预检(引擎 dk_risk/tier/earn_why 引用)+一句话初筛意见+初步方向倾向;\n"
                "   note 必须以\"AMC 初筛观察,不建仓\"开头(复盘按此标记不计命中),\n"
                "   entry_window_pst 写\"观察——建仓窗在 12:45 财报班\";\n"
                "   amc_tonight 名单为空的日子本槽才空槽(empty_reason=\"今日无 AMC\");\n"
                "   持仓腿纪律不变:财报伏击/持仓/手册在 12:45 财报班;\n"
                "   T+0 动量豁免(v3.25.3):当日出财报的票若盘中动量显著(market_movers/名单可见),\n"
                "   可入 S1/S3 出 T+0 动量卡——当日收盘前强制清仓,禁持过财报,\n"
                "   note 必须写\"T+0 财报票,收盘前清仓\"")
    return ("S2 财报伏击·今晚 AMC(财报班主攻位一):amc_tonight 名单择一,~12:50 PST 尾盘买入,\n"
            "   持过财报,次日盘初按结果处置(gap-and-go 续持/开盘即走);earnings_note 必须\n"
            "   含\"持过财报,IV crush 风险自担\"字样(次晨交班块靠\"持过财报\"识别过夜腿);\n"
            "   三档全摆硬规则(v3.25.3,Lyra 拍板 2026-08-20:机器不藏强票,选择权在交易员):\n"
            "   - 强票档(引擎 dk_risk=true,chg5>15% 或 rsi>75):照常出卡,强制标注\"双杀风险位\",\n"
            "     evidence 必须写双杀双向情景(冲高续涨与利好出尽下杀两个方向都给参照价带)+仓位提示;\n"
            "     放弃条件必须给盘后止损参照;\n"
            "   - 温和档(tier=run-up):财报前动量正、未过热,吃惯性;\n"
            "   - 超跌档(tier=oversold,chg5<-2%):财报前超跌,博利空出尽反弹(WOLF/JBSS 型);\n"
            "   三档各自评估、择优并排,rank_reason 写清档位对比与选档理由,买哪张交易员拍板;\n"
            "   尾盘形态硬规则(v3.27,8-25 INTU 案:当日 -2.92%、loc 0.17 收在最低仍被点成 call 持过财报,盘后 -7%):\n"
            "   amc_tonight 已按引擎 earn_score(因子分 0–100)排,earn_why 逐因子可查;call 只做 earn_score≥40 的票,\n"
            "   当日≤-1% 且 loc<0.5 的票点 call = 引擎作废;三档之上先看形态,再看档位;\n"
            "   事件层(v3.30):cross.regime.event 有 event_day=true 时——今日有高影响数据或巨头盘后财报:\n"
            "   T+0 只做明确放量票(引擎节奏线升到 1.0),持过财报的腿要写明巨头 gap 风险与对冲;仓位档已降一档,勿自行加仓;\n"
            "   资金确认硬规则(v3.27.1,Lyra:不在 FMP top mover 榜的不收):S2/S4 call 腿的票必须在当日\n"
            "   FMP 涨幅榜或最活跃榜(收涨)上(名单行 fmp_board=true),否则引擎作废;\n"
            "   质量地板硬规则(COTY 案后立,先于一切档位;v3.26 起为引擎级:amc_tonight 名单已是地板后幸存者,\n"
            "   筛除者在 floor_rejected.amc_tonight 逐票带条款;名单外点名 = 引擎作废卡,禁点):\n"
            "   price<$10 或 20 日成交额<地板 或无实测 禁入(无接盘仙股;PICS 案);\n"
            "   共识 Reduce/Sell 级、指引撤回、重大诉讼缠身的票禁入;evidence 必须给资金/量能实据\n"
            "   (实测量能读数或明确资金流向叙据,禁\"期权活跃\"式估计);\n"
            "   宁空勿弱硬规则:无过地板且证据充分的候选 = 出空槽卡(empty_reason 写筛除过程),\n"
            "   禁止为填槽选弱票——空槽优于弱腿;\n"
            "   无合格 AMC 标的时本槽回落 run-up 腿:upcoming_earnings 名单(未来 1-8 个交易日,days_out=1 为明日盘后出,\n"
            "   引擎已附读数)择一吃预期消化段,公布前必须离场(手册第二步);质量地板同样适用;\n"
            "   已出结果的财报票(今晨 BMO/昨夜 AMC gap)不属本槽——由 movers 硬闸强制显式处理,\n"
            "      够强则进 S1;\n"
            "   evidence 硬规则:必须引用所属板块当日读数(sector_leaders/sector_laggards 的 chg_pct/mom20),\n"
            "      候选板块与 sector_leaders 背离时必须在 rank_reason 写一句解释(为何逆板块仍做)")


def _s4_section(shift):
    base = ("S4 引擎位:由跨资产引擎读数驱动——领涨板块龙头、迁徙腿(divergence 证实)或\n"
            "   对冲腿(按 regime),evidence 必须引用引擎数字")
    if shift != "earnings":
        return base
    return ("S4 财报伏击·明日 BMO(财报班主攻位二;v3.25 新腿,EL 案根治):\n"
            "   bmo_tomorrow 名单(明日盘前出结果,引擎已附读数)择一,~12:50 PST 尾盘买入,\n"
            "   持过夜至明晨出数,明晨盘初按结果处置;earnings_note 必须含\"持过财报,\n"
            "   IV crush 风险自担\";三档全摆/质量地板/宁空勿弱三条硬规则与 S2 完全同判例\n"
            "   (强票档亮牌不禁入、超跌档合法、引擎地板 price<$10/成交额<地板/无实测 与 Reduce 共识禁入、\n"
            "   空槽优于弱腿;bmo_tomorrow 名单已是地板后幸存者,名单外点名 = 引擎作废卡);\n"
            "   无合格 BMO 标的时本槽回落引擎位\n"
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
        return ("财报手册本班停用——财报伏击/持仓腿在 12:45 财报班;当日财报票盘中动量可走\n"
                "T+0 豁免(收盘前强制清仓,禁持过夜)。候选若 5 个交易日内撞财报,仍须在\n"
                "earnings_note 写明日期/BMO 或 AMC(信息披露)。")
    return """财报两步手册(earnings_calendar 采集必须核对;候选撞财报必须在 earnings_note 声明):
- 第一步·财报/重大消息当日:禁开盘第一根追入——高 IV + 双向扫损 = 多空双杀;
  合法入场 = IV crush 落地后、盘初区间(约首30分钟)方向突破确认再进,0DTE 此时才合法
- 第二步·财报前 run-up(公布前 1-8 个交易日;days_out=1 即明日盘后出,只有一个交易日的窗):可做预期抢跑 call,买"预期+IV 双升"
  (vega 顺风);硬规则 = 财报公布前必须离场,赚 run-up 不赌事件;
  今日 AMC 出财报的标的,T+0 收盘前清仓(本来就是纪律,此处双重锁死)
- 第三步·财报次日(昨夜 AMC 已出结果,今晨 gap):IV 已 crush——单腿 call 的黄金窗口之一;
  gap-and-go = 盘初 30 分钟站稳开盘价上方再追;首 30 分钟回补 gap 过半 = fade,放弃做多;
  方向已被结果定调,禁逆结果抄底/摸顶
- 候选 5 个交易日内有财报 → earnings_note 写明日期/BMO 或 AMC/采用哪条手册;无则写"无"
今晚 AMC 规则(引擎 amc_tonight 名单必须核对,读数已附 rsi14/chg5_pct):
- 名单内标的走 S2 尾盘伏击腿(~12:50 PST 买入持过财报)或不做;
  除 S2/S4 伏击腿外禁持仓过财报;dk_risk=true 强票必须亮"双杀风险位"牌(不禁入,风险叙据齐备交拍板)
- 名单已按引擎 earn_score 降序(尾盘形态分,earn_why 逐项可查;不是市值序);前三按分逐票评估,
  未点名须在 rejected 或正文给一句理由;earn_score<40(因子分 0–100)的票禁做 call;
  引擎硬闸:call 点名当日≤-1% 且 loc<0.5 的票 = 作废卡(8-25 INTU 案),put 镜像同判
明日 BMO 规则(引擎 bmo_tomorrow 名单必须核对,读数已附 rsi14/chg5_pct):
- 名单内标的走 S4 BMO 伏击腿或不做;dk_risk 亮牌规则同 AMC;
- 名单已按 earn_score 降序(因子分 0–100);前三按分逐票评估,未点名须给一句理由;earn_score<40 禁做 call
未来财报 run-up(引擎 upcoming_earnings,未来 1-8 个交易日,days_out 逐票标注,cap 12,全票附读数):
- 作 S2 回落位供数;有预期消化段证据的票优先;公布前必须离场"""


_MIN_CANDS_RULE = (
    "候选下限硬规则(v3.25.6,Lyra 拍板 2026-08-20\"每跑一轮必须三个候选以上,拍板买不买的是我\"):\n"
    "- 每轮 candidates 非空卡≥3(四槽至少三个实质卡,空槽≤1);\n"
    "- 空槽唯一合法理由=质量地板不过(引擎地板 price<$10 或 20 日成交额<地板 或无实测/Reduce-Sell 共识/\n"
    "  指引撤回/重大诉讼);引擎作废的卡自动计入 no_candidate_reason(条款可审);\n"
    "- 禁止用\"动量不显著\"\"默认收敛\"\"不硬凑\"\"超卖不追空\"作为空槽或否决候选存在的理由——\n"
    "  这些是时机/方向判断,写进对应卡的入场条件与放弃条件,不是不出卡的理由;\n"
    "- S1 主池:趋势对齐+当日有动量+流动性过闸=必须出卡,禁\"默认收敛\";\n"
    "- S3 事件:8-K/FDA/异动榜命中+流动性过闸=必须出卡;超卖是时机过滤(入场条件写回踩确认),\n"
    "  不是方向否决;\n"
    "- 质量地板一条不松(防 COTY 弱票填槽):地板过+有证据=出卡,买不买交易员拍板;\n"
    "- 兜底:某轮真无合格候选(<3)时,必须输出 no_candidate_reason 字段,逐票写清被地板筛除的\n"
    "  标的与筛除条款,列数≥3 才算数——禁止无痕全空。")


def _shift_block(shift, todays):
    parts = []
    if shift == "morning":
        parts.append("昨夜交班义务(v3.25):引擎读数 handover 块 = 昨夜过夜伏击腿与昨日 watch 的盘初实测。"
                     "overnight_legs 必须首屏逐腿处置(gap-and-go 续持/开盘即走,写进 macro.logic 或对应候选);"
                     "watch_tape 有显著变化(|chg_pct|≥3%)的必须点名;昨日战绩 rejected_review 里 "
                     "flag_misskill=true(被否却涨>2%)的必须一句话复盘误杀原因。")
        parts.append("本班纪律:不出财报持仓腿——AMC/BMO 伏击、run-up 在 12:45 财报班;"
                     "当日财报票盘中动量走 T+0 豁免(可入 S1/S3,收盘前强制清仓,禁持过夜)。")
    elif shift == "midday":
        parts.append("本班定位(盘中复核班):①逐腿复核今晨在案腿(见下方在案腿)——持有/止损/离场校正,"
                     "写进对应槽 note 或 conclusion;②主池/事件按候选下限硬规则正常出卡(全视野);"
                     "③今晚 AMC 初筛(见 S2 说明)。新卡入场窗以本班时点起算。")
    else:
        parts.append("本班定位(财报班,开卷):当日数据已全。主攻两腿 = S2 今晚 AMC 伏击 + S4 明日 BMO 伏击,"
                     "入场窗同为 12:50-12:55 PST 尾盘;两腿并排、只择一执行(过夜敞口规则见 S4);"
                     "upcoming_earnings(1-8 日窗,days_out=1 为明日盘后出)为 S2 回落位供数。今晨/盘中在案腿只做收尾提示(13:00 收盘硬平仓),不重复出卡。"
                     "S1/S3 本班 = 明晨预排观察卡(v3.26,8-24 案:本班距收盘 15 分钟,DS 曾出 PATH 10 分钟 0DTE 刮单——禁):"
                     "S1 从 candidate_pool 按分取(全日 K 线已定型,是次日晨会最好的预排材料),S3 取 8-K/FDA 事件票;"
                     "两卡 note 必须以\"明晨预排,不建仓\"开头,entry_window_pst 写\"明晨 06:45 班盘初确认后\","
                     "expiry 写\"明晨定\",禁 0DTE、禁今日尾盘入场;预排卡复盘进 watch 不计命中。")
    if shift in ("morning", "midday", "earnings"):
        parts.append(_MIN_CANDS_RULE)   # evening=复盘班不出候选卡,不挂(2026-08-21 范围审定)
        parts.append("晚报调优的效力边界(2026-08-24 立):prev_review 里的调优段仅供参考——"
                     "其中的机械阈值类内容(RSI 数值闸/新禁入条件/入场区间)一律无效,"
                     "在册规则以本 prompt 条款为准;晚报无立法权,新增规则只能由 Lyra 拍板入 prompt。"
                     "调优段里的观察点/降权建议可参考,但每一票仍按本班在册条款独立评估。")
    if todays:
        parts.append("今日已出班次在案腿:" + json.dumps(todays, ensure_ascii=False)[:1600])
    return "\n".join(parts)


def load_fault_lines_snapshot(today):
    """S1 缝(戌现场施工 2026-08-24 回流):读 inbox/factor_snapshot.json 的 fault_lines 块,
    渲染成事实行字符串。DS prompt 标"结构参考,非信号"。
    返回 (fact_str, block_dict);无文件或无断层位 → ("", {})。"""
    inbox = os.path.join(OUT, "inbox", "factor_snapshot.json")
    if not os.path.isfile(inbox):
        return "", {}
    try:
        payload = json.loads(open(inbox, encoding="utf-8").read())
    except Exception:
        return "", {}
    block = payload.get("fault_lines") or {}
    if not block.get("available"):
        return "", block
    syms = block.get("symbols") or []
    if not syms:
        return "", block
    lines = ["[断层热力 · 结构参考,非信号 · %s]" % block.get("date", today)]
    for s in syms:
        sym = s.get("symbol")
        parts = []
        f1 = s.get("F1_gamma_flip")
        if f1 is not None:
            parts.append("F1 gamma翻转@%s" % f1)
        f2 = s.get("F2_oi_walls") or {}
        cw = f2.get("call") or []
        pw = f2.get("put") or []
        if cw:
            parts.append("F2 call墙%s" % cw)
        if pw:
            parts.append("F2 put墙%s" % pw)
        mp = s.get("F2_max_pain")
        if mp is not None:
            parts.append("max_pain@%s" % mp)
        f3 = s.get("F3_gap_edge")
        if f3:
            parts.append("F3 gap边[%s,%s]" % (f3.get("lower"), f3.get("upper")))
        f4 = s.get("F4_iv_inversion") or {}
        if f4 and f4.get("inverted"):
            parts.append("F4 IV倒挂(ratio=%s)" % f4.get("ratio"))
        if s.get("near_fault"):
            parts.append("⚠盘前贴断层")
        if parts:
            lines.append("%s: %s" % (sym, " · ".join(parts)))
    if len(lines) <= 1:
        return "", block
    return "\n".join(lines), block


def build_trading_prompt(raw, ws, yday, cross=None, prev=None, shift="morning", todays=None, fault_lines=""):
    _fl = ("\n断层热力(结构参考,非信号):\n" + fault_lines + "\n") if fault_lines else ""
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
{_fl}
交易风格偏置(硬约束):交易员主做 T+0 单腿 CALL,当日了结。
- 策略默认形态 = 单腿 CALL,到期选 0DTE 或最近可用到期,必须给 t0_exit(当日平仓纪律)
- PUT 仅当看空证据明确时才提,并在 evidence 写清依据;禁止多腿组合;禁止编造权利金/报价
候选硬规则:每个候选必须锚定隔夜采集中的具体条目,逐条给出处;禁止凭训练记忆点名。
四槽股票卡制(2026-08-07 Lyra 定;candidates 必须恰好 4 条,slot 1-4 各一,
全部 单腿 CALL · T+0):
S1 主池·引擎候选池(v3.26,2026-08-24 案:六眼只当参考、S1 由 DS 自由挑,挑出热簇里 +1.77% 的
   PATH 做 10 分钟 0DTE,最活跃+🔥团的 BMNR 没进卡):候选视野 = 引擎 candidate_pool——
   七眼并集(异动榜/最活跃/🔥同频团/🔥热簇/连涨/自选/趋势榜)只决定谁进宇宙;排序 = 六因子核 0–100
   (F1 资金密度=换手率 / F2 趋势 / F3 尾盘形态 / F4 距财报天数 / F5 期权 γ/|θ| 不对称性 / F6 风险扣分;score_why 逐因子可查)
   →逐票实测→硬地板(price≥${fetchers.pool_price_floor():g}、
   20 日成交额≥${fetchers.pool_adv_floor_usd() / 1e6:.0f}M 实测,无实测不入池)→透明计分(score_why 逐项可查)→按分排序;
   禁止只在板块 ETF 成分逻辑内选,sector_leaders 只作背景;
   硬规则:①S1 ticker 必须在 candidate_pool 内(池外点名引擎盖章"视野外");
   ②池前三(按 score)必须逐票评估——入卡,或 rejected 一句话理由(趋势不对齐/RSI 过热/追高
   均为合法理由),禁无痕跳过;ETF 已由引擎硬排不入池(IV 结构不适合单腿 call),S1/S3 点名
   ETF = 引擎作废卡;③rank_reason 引用该票 score 与 score_why;
   ④候选池为空时本槽空槽,empty_reason 引用 pool_rejected 的筛除条款;
   ⑤flags 含"追高风险"/"过热"的票入场条件必须写回踩确认;
   优选距 52 周高 <5% 强势票(high52_dist_pct);trend_regime=下降趋势 时
   做多降杠杆表述并写明逆势理由,或让位防守
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
- 热簇·数据自聚(引擎 theme_heat):当日榜单标的按行业标签自动聚簇,非预设名单——
  hot=true 的簇=钱正往那个行业走,成员(实测涨跌已附)是 S1/S3 一等候选源
- 同频簇(引擎 comove_clusters):极大团——簇内任意两成员近 10 日收益 ρ≥0.7,
  "两两都在动"而非"在同一个朋友圈"(传递串链不成簇);hot=≥2 名资金确认+当日
  中位数与六成成员同时达标;跨行业标签自然合流;成员与热簇成员同等逐票必评
- 最活跃榜(引擎 most_active):成交最活跃=热资金所在,稳步流(+3~8%)在这里不在暴动榜
- 连涨榜(引擎 streak_board):近 3 日 ≥2 次上榜=趋势型资金流,movers 尖峰榜的盲区
- 全市场异动榜(引擎 market_movers,非仅财报):|chg_pct|≥10% 的标的必须在 macro.logic 或
  conclusion 点名成因与板块含义;事件驱动个股可入 S3 评估(过流动性闸);禁止无痕跳过
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


def build_evening_prompt(raw, yday, cross=None, review=None, inventory=None, today=None):
    if today:
        _iso = _next_trading_day(today)
        ntd = "%s(周%s)" % (_iso, "一二三四五六日"[datetime.date.fromisoformat(_iso).weekday()])
    else:
        ntd = "下一交易日"
    return f"""你是交易台参谋。当前 {fetchers.et_now_hm()} ET(收盘后;今日 AMC 财报已披露)。
日历纪律:下一交易日 = {ntd}(周末/隔日自动换算,联邦假日请自行核对)。全篇前瞻表述
一律写"下一交易日({ntd})",禁止裸用"明日/明晨/明天"——周五晚报写"明晨"实指周一,
歧义已出过事故。
调优边界:调优段只准提观察点、降权建议、复核请求;禁止立机械阈值新规
(RSI 数值闸/禁入条件/入场区间等)——那是把时机判断写成规则,立法权在 Lyra,
晚报建议不会也不应被晨会当作在册条款执行。
候选/地板/ETF 纪律(与白班同判,v3.26.3):下一交易日弹药、run-up 点名、过夜腿讨论只准在
candidate_pool(引擎候选池,已过地板按分排序,score_why 逐项)与地板后的 amc_tonight/bmo_tomorrow/
upcoming_earnings 内点名;floor_rejected / pool_rejected 里的票只可作"已被引擎地板筛除(条款)"一笔带过,
禁当过夜腿/弹药/跟进对象;ETF(IBIT/BITO/TSLL/SOXL 类)禁作候选与"值得盯"对象(对冲工具除外);
amc_results_health 是盘后读数健康态(k/n 出数+缺数原因),缺数只讲事实,禁猜盘后涨跌。
写今日收盘复盘 + 下一交易日弹药,给交易员看:
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
   amc_results 是实测盘后涨跌(Nasdaq 报价,时点快照)——|盘后|≥8% 者必须重点讲清,
   但盘后快照只述事实,禁止据此对持仓腿下成败结论(盘后薄量摆动大,深夜字段语义待定案);
   过夜腿成败以次晨交班块处置窗实测为准,
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
    payload = {"model": DS_MODEL, "max_tokens": int(os.getenv("DS_MAX_TOKENS", "12000")),
               "think": False,   # Ollama(deepseek-v4-pro:cloud)必需;官方 OpenAI 兼容端忽略未知字段
               "messages": [{"role": "user", "content": prompt}]}
    headers = {"Authorization": "Bearer " + key}
    # 5xx 重试 + 空内容兜底(戌现场施工 2026-08-24 回流;2026-08-20 晚报 500 根因:单发无重试)
    import time as _t, socket as _sock
    last_err = None
    # v3.26.3(戌 8-24 抓:今晨 6:45 DS 超时 120s 崩班,html 没覆盖):超时 env DS_TIMEOUT 默认 420s
    # (12000-16000 token 输出实测常超 120s),超时类异常再试一次;仍败向上抛,由 main 接住落失败标记
    to = int(os.getenv("DS_TIMEOUT", "420"))
    for attempt in range(3):
        try:
            r = _http(DS_BASE + "/chat/completions", payload, headers, timeout=to)
            content = r.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
            if content.strip():
                return content
            if attempt == 0:
                payload.pop("think", None)
                print("[scout] ds 空内容,去 think 重试")
                continue
            print("[scout] ds 空内容(第 %d 次),继续重试" % (attempt + 1))
        except Exception as e:
            last_err = e
            code = getattr(e, "code", None)
            if code and 500 <= code < 600 and attempt < 2:
                print("[scout] ds HTTP %d,退避重试(%d/3)" % (code, attempt + 1))
                _t.sleep(2 * (attempt + 1))
                continue
            is_to = isinstance(e, (_sock.timeout, TimeoutError)) or \
                isinstance(getattr(e, "reason", None), (_sock.timeout, TimeoutError)) or "timed out" in str(e)
            if is_to and attempt == 0:
                print("[scout] ds 超时(%ds),重试一次" % to)
                continue
            raise
    if last_err:
        raise last_err
    return ""


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


_FLOOR_BAN_WORDS = ("默认收敛", "动量不显著", "不硬凑", "超卖不追空")


def apply_candidate_floor(ds, shift):
    """规则 B 代码闸(v3.25.7 重建+v3.25.8 补 earnings;evening 复盘班不挂):
    三种违例只盖章(_floor_violation 进 json+skips),不改 DS 的卡。
    ①非空卡<3 且 no_candidate_reason 缺失或列票<3;②空槽>1;③空槽理由用禁词。"""
    if shift not in ("morning", "midday", "earnings") or not isinstance(ds, dict):
        return ds
    cands = ds.get("candidates") or []
    nonempty = [c for c in cands if not c.get("empty")]
    empties = [c for c in cands if c.get("empty")]
    v = []
    if len(nonempty) < 3:
        ncr = str(ds.get("no_candidate_reason") or "")
        listed = len(re.findall(r"[A-Z]{1,5}", ncr))
        if listed < 3:
            v.append("非空卡 %d<3 且 no_candidate_reason 未逐票列筛除(仅 %d 票)" % (len(nonempty), listed))
    if len(empties) > 1:
        v.append("空槽 %d>1" % len(empties))
    for c in empties:
        hit = [w for w in _FLOOR_BAN_WORDS if w in str(c.get("empty_reason") or "")]
        if hit:
            v.append("slot%s 空槽理由用禁词%s" % (c.get("slot"), hit))
    if v:
        ds["_floor_violation"] = v
        for x in v:
            print("[scout] 候选下限违例(盖章不改卡):", x)
    return ds


def _floor_clause(row):
    """质量地板判据(v3.26,引擎级,三处同判:财报名单/候选池/DS 点名)。
    row 带 price / adv20_usd(fetchers._derive 实测:价格=末根收盘;成交额=前 20 根 close×volume 均值)。
    返回 None=过地板,否则一句筛除条款。无实测 = 不过(不装数):没有成交额读数的票不进推荐。"""
    pf, af = fetchers.pool_price_floor(), fetchers.pool_adv_floor_usd()
    px, adv = row.get("price"), row.get("adv20_usd")
    if px is None:
        return "无价格实测"
    if px < pf:
        return "price $%.2f<$%g 地板" % (px, pf)
    if adv is None:
        return "20日成交额无实测(样本%s根<5)" % (row.get("adv20_days") if row.get("adv20_days") is not None else "?")
    if adv < af:
        return "20日成交额 $%.0fM<$%.0fM 地板" % (adv / 1e6, af / 1e6)
    return None


def floor_earnings_lists(cross):
    """财报三名单过引擎地板(v3.26,PICS 案:$5 级 AMC 票靠"名单前三须点名"规则被 DS 点成 S2 RANK 2,
    流动性"无实测"照样出卡)。amc_tonight / bmo_tomorrow / upcoming_earnings 就地改为幸存者,
    筛除者进 cross["floor_rejected"][名单] 逐票带条款(渲染/复盘可审,不无痕)。"""
    rej = cross.setdefault("floor_rejected", {})
    board = fmp_board_syms(cross)   # v3.27.1:FMP 当日涨榜/最活跃榜(收涨)= 资金确认
    for k in ("amc_tonight", "bmo_tomorrow", "upcoming_earnings"):
        rows = cross.get(k)
        if not isinstance(rows, list):
            continue
        keep, drop = [], []
        for x in rows:
            if not isinstance(x, dict):
                keep.append(x)
                continue
            cl = _floor_clause(x)
            if cl:
                drop.append({"symbol": x.get("symbol"), "clause": cl, "price": x.get("price")})
            else:
                x["fmp_board"] = x.get("symbol") in board      # v3.29:只标记(资金已由 F1 计),不再加分
                keep.append(x)
        cross[k] = _sort_earn(keep)
        rej[k] = drop
    return cross


def fmp_board_syms(cross):
    """FMP 当日"钱的榜":涨幅榜(gainers 侧)∪ 最活跃榜中当日收涨者。Lyra 2026-08-25:测出来的票不在 FMP top mover 榜
    = 不收。作为财报 call 腿的硬门与名单加分的判据;两榜都失败时返回空集(下游作废条款会写明"榜缺失")。"""
    out = set()
    for x in (cross.get("market_movers") or []):
        if isinstance(x, dict) and x.get("side") == "gainers" and x.get("symbol"):
            out.add(str(x["symbol"]).upper())
    for x in (cross.get("most_active") or []):
        if isinstance(x, dict) and x.get("symbol") and (x.get("chg_pct") or 0) > 0:
            out.add(str(x["symbol"]).upper())
    for x in (cross.get("trend_board") or []):      # v3.28:自算趋势榜同为"钱的榜"
        if isinstance(x, dict) and x.get("symbol"):
            out.add(str(x["symbol"]).upper())
    return out


_TREND_CAP = 20


def attribution_rows(cross, data, shift):
    """池前 12(role=pool)+ 非空实卡(role=card,预排/初筛不记)→ 归因行。"""
    rows = []
    view = "t0" if shift in ("morning", "midday") else "swing"
    for i, p in enumerate((cross.get("candidate_pool") or [])[:12]):
        rows.append({"symbol": p.get("symbol"), "role": "pool", "rank": i + 1, "score": p.get("score"), "view": view,
                     "subs": p.get("subs"), "price": p.get("price"), "direction": None, "slot": None})
    for c in (data or {}).get("candidates") or []:
        if not isinstance(c, dict) or c.get("empty"):
            continue
        note_all = "%s %s" % (c.get("note") or "", (c.get("strategy") or {}).get("note") or "")
        if "预排" in note_all or "初筛观察" in note_all:
            continue
        t = str(c.get("ticker") or "").upper()
        pr = next((p for p in (cross.get("candidate_pool") or []) if p.get("symbol") == t), None)
        tc = c.get("tape_check") or {}
        st = c.get("strategy") if isinstance(c.get("strategy"), dict) else {}
        rows.append({"symbol": t, "role": "card", "rank": c.get("rank"), "score": (pr or {}).get("score"), "view": view,
                     "subs": (pr or {}).get("subs"), "price": tc.get("price") or (pr or {}).get("price"),
                     "direction": str(c.get("direction") or "").lower(), "slot": c.get("slot"),
                     "entry_window": st.get("entry_window_pst"), "exit_window": st.get("exit_window_pst"), "expiry": st.get("expiry")})
    return [r for r in rows if r.get("symbol") and r.get("price")]


def evening_feedback(cross, today):
    """v3.31 晚班反馈回路:①结算归因账本(当日 t0 用收盘;昨日 swing 用今收);②因子表现表进 cross;③池前 20 数据自检(Alpaca 第二源)。
    全部落 cross,渲染成两行;失败响亮不装数。"""
    out = {"resolved": 0, "report": None, "selfcheck": None}
    try:
        syms = set()
        for r in attribution.load_rows(OUT, days=5):
            syms.add(r["symbol"])
        syms |= {p["symbol"] for p in (cross.get("candidate_pool") or [])[:20]}
        snaps = fetchers.quote_layer_snapshot(sorted(syms)[:120], with_rsi=False) if syms else {}
        closes = {k: v["price"] for k, v in snaps.items() if v.get("price")}
        out["resolved"] = attribution.resolve(OUT, today, closes, next_close_by_sym=closes, opt_fn=option_pnl_fn(today))
        out["report"] = attribution.factor_report(OUT, days=20)
        cross["factor_report"] = out["report"]
        cross["factor_report_line"] = attribution.report_line(out["report"])
        # 数据自检:池前 20 的 FMP 收盘 vs Alpaca 最新日线
        def _sec(sym):
            rows_, _ = fetchers._alpaca_history(sym)
            if rows_:
                r_ = rows_[-1]
                return r_.get("date"), float(r_.get("c") or 0)
            return None
        top = [p["symbol"] for p in (cross.get("candidate_pool") or [])[:20]]
        prim = {}
        for s_ in top:
            rows_, _ = fetchers._history(s_)
            if rows_:
                prim[s_] = float(rows_[-1]["c"])
        out["selfcheck"] = attribution.data_selfcheck(top, prim, _sec, tol_pct=float(os.getenv("SELFCHECK_TOL_PCT", "0.5")))
        cross["data_selfcheck"] = out["selfcheck"]
        for m in out["selfcheck"]["mismatch"]:
            fetchers._log_skip("data_selfcheck", m["symbol"], "FMP %.2f vs Alpaca %.2f(%s)偏差 %.2f%%" % (m["primary"], m["secondary"], m["secondary_date"], m["dev_pct"]))
        print("[scout] 反馈回路:结算 %d 行;%s;自检 %d 票 偏差 %d 缺第二源 %d" % (out["resolved"], cross["factor_report_line"], out["selfcheck"]["checked"], len(out["selfcheck"]["mismatch"]), out["selfcheck"]["unavailable"]))
    except Exception as exc:
        print("[scout] 反馈回路异常:", exc)
        cross["factor_report_line"] = "反馈回路异常:%s" % str(exc)[:100]
    return out


def option_pnl_fn(today):
    """卡的期权结算函数:Theta 历史 greeks/all(带 bid/ask)按入场窗起点/出场窗终点取 ATM call 中价。
    端点形状与 fetchers.theta_option_mid_at 同步;不可用 → (None, 原因)。"""
    def fn(row):
        if not hasattr(fetchers, "theta_option_mid_at"):
            return None, "无 theta_option_mid_at"
        ew, xw = row.get("entry_window") or "", row.get("exit_window") or ""
        t_in = _first_time(ew); t_out = _last_time(xw) or (12, 50)
        if not t_in:
            return None, "入场窗无时刻"
        exp = today if (row.get("expiry") or "").upper().startswith("0DTE") else None
        if not exp:
            return None, "非 0DTE 卡,本版只结算 0DTE"
        r = fetchers.theta_option_mid_at(row["symbol"], exp, float(row["price"]), t_in, t_out)
        if not r:
            return None, "Theta 无历史报价"
        if not r.get("mid_in") or not r.get("mid_out"):
            return None, "中价缺:%s" % r
        return round((r["mid_out"] / r["mid_in"] - 1) * 100, 1), "strike %s in %.2f out %.2f" % (r.get("strike"), r["mid_in"], r["mid_out"])
    return fn


def _first_time(text):
    m = _TIME_RX.search(text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def _last_time(text):
    ms = _TIME_RX.findall(text or "")
    return (int(ms[-1][0]), int(ms[-1][1])) if ms else None


_MEGA_CAP_B = float(os.getenv("EVENT_MEGACAP_B", "500"))     # 市值 ≥ 此值(十亿)的财报 = 全市场事件


def event_layer(payload, today):
    """v3.30(2026-08-26,Lyra:"我说过今天 NVDA 财报、几个美国关键数据、美债油价一个没考虑,你完全没有自己的思考"):
    事件层——把 raw 里本来就有、却从没进过判断的东西接进判断:
    ① 宏观日历(economic_calendar):今日 US 高影响发布(impact High/Medium 或事件名含 CPI/PCE/GDP/Payroll/FOMC/Fed/Jobless);
    ② 巨头财报(earnings_calendar 原始行,市值 ≥ EVENT_MEGACAP_B):今日 AMC / 明日 BMO;
    ③ 美债:treasury_yields 10Y 水平;fred/indices 若有 5 日变化则带上;④ 油:commodities WTI 当日涨跌。
    输出 {today_events, megacap_amc, megacap_bmo, y10, y10_chg_bp, wti_chg_pct, event_day(bool), why}。
    只判"是不是事件日"与显示读数;怎么用由 regime 与闸决定,不替 Lyra 定仓位。"""
    m = {}
    for src in payload.get("results", payload.get("sources", [])):
        m[src.get("source")] = src
    out = {"today_events": [], "upcoming_events": [], "megacap_amc": [], "megacap_bmo": [], "y10": None, "y10_chg_bp": None,
           "wti_chg_pct": None, "event_day": False, "why": []}
    # ① 宏观日历
    kw = ("CPI", "PCE", "GDP", "PAYROLL", "NONFARM", "FOMC", "FED ", "FEDERAL FUNDS", "JOBLESS", "UNEMPLOYMENT", "RETAIL SALES", "ISM", "PMI")
    nd = _next_trading_day(today)
    nd = nd.isoformat() if hasattr(nd, "isoformat") else str(nd)[:10]
    for it in (m.get("economic_calendar") or {}).get("items") or []:
        ev = str(it.get("event") or "")
        hi = str(it.get("impact") or "").lower() in ("high", "medium") or any(k in ev.upper() for k in kw)
        if not hi:
            continue
        d = str(it.get("date") or "")[:10]
        row = {"date": it.get("date"), "event": ev, "impact": it.get("impact"), "actual": it.get("actual"), "estimate": it.get("estimate")}
        if d == today:
            out["today_events"].append(row)
        elif d > today:
            out["upcoming_events"].append(row)
    out["upcoming_events"] = out["upcoming_events"][:8]
    # ② 巨头财报(原始日历,未过地板)
    for it in (m.get("earnings_calendar") or {}).get("items") or []:
        try:
            sym = str(it.get("symbol") or "").upper()
            mc = it.get("marketCap") or it.get("market_cap") or ""
            mcb = float(str(mc).replace("$", "").replace(",", "") or 0) / 1e9 if mc else 0.0
        except Exception:
            continue
        if mcb < _MEGA_CAP_B or not sym:
            continue
        d = str(it.get("date") or "")[:10]
        when = str(it.get("time") or it.get("when") or "").lower()
        if d == today and ("after" in when or "amc" in when):
            out["megacap_amc"].append({"symbol": sym, "mcap_b": round(mcb)})
        elif nd and d == nd and ("pre" in when or "bmo" in when):
            out["megacap_bmo"].append({"symbol": sym, "mcap_b": round(mcb)})
    # ③ 10Y
    try:
        for it in (m.get("treasury_yields") or {}).get("items") or []:
            if str(it.get("field") or "").strip().lower() in ("10 yr", "10yr", "10 year"):
                out["y10"] = float(it.get("value"))
    except Exception:
        pass
    # ④ WTI
    for it in (m.get("commodities") or {}).get("items") or []:
        if it.get("name") == "WTI":
            out["wti_chg_pct"] = it.get("chg_pct")
    # 判定
    if out["today_events"]:
        out["why"].append("今日数据:" + " / ".join(e["event"] for e in out["today_events"][:4]))
    if out["megacap_amc"]:
        out["why"].append("巨头盘后:" + " ".join("%s($%dB)" % (x["symbol"], x["mcap_b"]) for x in out["megacap_amc"]))
    if out["megacap_bmo"]:
        out["why"].append("明晨巨头:" + " ".join(x["symbol"] for x in out["megacap_bmo"]))
    if out["wti_chg_pct"] is not None and abs(out["wti_chg_pct"]) >= 3:
        out["why"].append("油 %+.1f%%" % out["wti_chg_pct"])
    if out["y10"] is not None:
        out["why"].append("10Y %.2f%%" % out["y10"])
    out["event_day"] = bool(out["today_events"] or out["megacap_amc"])
    return out


def regime_and_kelly(payload):
    """v3.29:VIX → 仓位档(满/半/停,只显示);复盘账本最近 20 份 → Kelly 分数(只显示)。"""
    m = {}
    for src in payload.get("results", payload.get("sources", [])):
        if src.get("source") in ("indices", "hedge_assets"):
            for it in src.get("items", []):
                if isinstance(it, dict) and it.get("name"):
                    m[it["name"]] = it
    vix = m.get("VIX") or {}
    tier, why = factors.regime_tier(vix.get("price") or vix.get("last"), vix.get("chg_pct"))
    ev = event_layer(payload, fetchers.trading_date().isoformat())
    if ev.get("event_day") and tier in ("满", "半"):
        tier = "半" if tier == "满" else "停"
        why += ";事件日降一档(" + ";".join(ev["why"][:2]) + ")"
    if ev.get("wti_chg_pct") is not None and ev["wti_chg_pct"] >= 3 and tier == "满":
        tier = "半"; why += ";油 %+.1f%% 降一档" % ev["wti_chg_pct"]
    hits = misses = 0
    try:
        files = sorted(f for f in os.listdir(os.path.join(OUT, "briefs")) if f.endswith("-review.json"))[-20:]
        for f in files:
            doc = json.load(open(os.path.join(OUT, "briefs", f), encoding="utf-8"))
            for leg in doc.get("legs") or []:
                if leg.get("hit") is True: hits += 1
                elif leg.get("hit") is False: misses += 1
    except Exception:
        pass
    frac, note = factors.kelly_fraction(hits, misses)
    return {"tier": tier, "why": why, "kelly_fraction": frac, "kelly_note": note, "hits": hits, "misses": misses, "event": ev}


def earnings_days_map(cross):
    """symbol → 距下一财报交易日数(0=今日 AMC,1=明日 BMO,其余按 upcoming days_out);F4 用。"""
    m = {}
    for x in (cross.get("amc_tonight") or []):
        if isinstance(x, dict) and x.get("symbol"):
            m[x["symbol"]] = 0
    for x in (cross.get("bmo_tomorrow") or []):
        if isinstance(x, dict) and x.get("symbol"):
            m.setdefault(x["symbol"], 1)
    for x in (cross.get("upcoming_earnings") or []):
        if isinstance(x, dict) and x.get("symbol") and x.get("days_out") is not None:
            m.setdefault(x["symbol"], int(x["days_out"]))
    return m


def _f5_cache_path(key):
    return os.path.join(OUT, "state", "f5-%s.json" % key)


def f5_batch(snaps, symbols, *, allow_afterhours=False):
    """F5:对一批候选取 Theta ATM call 的 gamma/|theta|,批内百分位。
    盘中 = 实时快照;盘外 = 读 16:45 盘后快照班落的 state/f5-<最近收盘日>.json(昨收 γ/|θ|,带 stale 标),
    两者都无 → None(因子缺,权重归一化,不装数)。返回 (sub_by_sym, raw_by_sym, source)。"""
    raws, source = {}, "live"
    if fetchers.is_rth_now() or allow_afterhours:
        for s_ in symbols:
            d = snaps.get(s_) or {}
            g = fetchers.theta_atm_call_greeks(s_, d.get("price"), allow_afterhours=allow_afterhours)
            raws[s_] = factors.f5_options_ratio(g)
    else:
        key = _last_closed_session(fetchers.trading_date().isoformat())
        try:
            doc = json.load(open(_f5_cache_path(key), encoding="utf-8"))
            cached = doc.get("ratios") or {}
            raws = {s_: cached.get(s_) for s_ in symbols}
            source = "eod:" + key
        except Exception:
            raws = {s_: None for s_ in symbols}
            source = "none"
    return factors.f5_options_batch(raws), raws, source


def f5_persist(key, raws, details=None):
    """盘后快照班(19:45 ET,当日快照仍在)把候选并集的 γ/|θ| 落盘,供次晨盘前/晚班趋势榜回退。"""
    try:
        os.makedirs(os.path.dirname(_f5_cache_path(key)), exist_ok=True)
        json.dump({"key": key, "ratios": raws, "details": details or {}, "n": sum(1 for v in raws.values() if v is not None)},
                  open(_f5_cache_path(key), "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass


def _last_closed_session(today, now_et=None):
    """趋势榜的键:最近一根已收盘日线的日期。判据 = ET 时刻是否已过 *today 这一天* 的 16:05,不是"现在几点"——
    21:00 PST 晚班的 ET 墙钟是次日 00:xx,trading_date 仍是 today;按"几点"判会把键错标成前一天
    (v3.28.2 自审抓获:那样晚班算的是昨日榜,次晨 06:45 又得重算 1200 票,"晚班算晨班共用"落空)。
    晚班(ET 次日 00:xx)→ today;次晨 06:45(ET 09:45,trading_date=次日)→ prev(次日)= today:同一键,零 GET。"""
    now_et = now_et or fetchers.now_et()
    cutoff = datetime.datetime.combine(datetime.date.fromisoformat(today), datetime.time(16, 5), tzinfo=now_et.tzinfo)
    if now_et >= cutoff:
        return today
    return fetchers.prev_trading_day(datetime.date.fromisoformat(today)).isoformat()


def trend_board(today):
    """v3.28(Lyra 2026-08-25:BMNR 涨了快一周从来不在榜上——FMP 涨幅榜按单日 % 排,壳票 +80% 占满;最活跃榜按
    股数排,$300 的票 $2B 成交额也进不了;两榜天生看不见"每天 +3%、连涨一周、成交额十亿"的趋势票):
    第七只眼,自算,不靠 FMP 榜——宇宙 = FMP screener 全市场普通股(日缓存)→ 历史日线快照(不打 quote,
    缓存新鲜零 GET)→ 硬地板(price/adv20,与候选池同判)→ 趋势分(整数,逐项落 json)→ cap 20。
    趋势分:近 5 日收涨 ≥4 根 +2(≥3 根 +1)/ 5 日 +5~+40% +2((2,5) +1;>40% +1 标追高)/ 10 日 ≥+10% +1 /
    RSI 55–80 +1(>85 -1)/ 放量 vol_x20≥1.2 +1 / 距 52 周高 ≥-10% +1 / 末根收高位 loc≥0.6 +1 / 末根收涨 +1;
    入榜最低 5 分(至少三路信号)。结果按 最近已收盘日 键落 state/trend_board-<日>.json,同日各班共用。
    可证伪:宇宙抓取失败 → 榜空并 skip 有条款;全宇宙不过地板 → 榜空;单日暴涨壳票不进(地板);连涨但成交额不足不进。"""
    key = _last_closed_session(today)
    path = os.path.join(OUT, "state", "trend_board-%s.json" % key)
    try:
        doc = json.load(open(path, encoding="utf-8"))
        if isinstance(doc, dict) and isinstance(doc.get("board"), list):
            return doc["board"], doc.get("universe_n", 0), doc.get("rejected_n", 0)
    except Exception:
        pass
    universe = fetchers.fetch_screener_universe()
    if not universe:
        return [], 0, 0
    snaps = fetchers.history_snapshot(universe, need_date=key)   # 缓存最新 bar 必须 ≥ 键日,否则重拉(晚班拉当日终盘)
    # 覆盖率自证:末根日期 = 键日的票占比。FMP 若尚未发布当日 EOD(晚班 00:xx ET 可能撞上),快照仍是前一日——
    # 此时算出的榜不得以当日键落盘,否则次晨读到的是陈榜且不会重算;不落盘、榜照用、日志响亮
    dated = sum(1 for d in snaps.values() if d.get("last_bar_date") == key)
    coverage = dated / max(1, len(snaps))
    board, rejected = [], 0
    # v3.29:趋势榜 = 因子核的趋势视角——F2(趋势子分)≥ TREND_F2_MIN(默认 60)且总分 ≥ TREND_MIN_SCORE(默认 55);
    # F5 盘外为空(晚班算),F4 用 upcoming 名单缺席时为 None——都按"因子缺"归一化,不装数
    min_score = int(os.getenv("TREND_MIN_SCORE", "55"))
    f2_min = float(os.getenv("TREND_F2_MIN", "60"))
    ind = fetchers.industry_lookup([s_ for s_ in universe if snaps.get(s_) and not _floor_clause(snaps[s_])])   # 只查过地板的票
    f5_sub, f5_raw, f5_src = f5_batch(snaps, [s_ for s_ in universe if snaps.get(s_) and not _floor_clause(snaps[s_])][:60])
    for sym in universe:
        d = snaps.get(sym)
        if not d or _floor_clause(d):
            rejected += 1
            continue
        info = ind.get(sym) if isinstance(ind.get(sym), dict) else {}
        if d.get("mcap_b") is None and info.get("mktcap_b"):
            d["mcap_b"] = info["mktcap_b"]
        if info.get("is_etf") is not False:            # 趋势榜同样禁 ETF/类型未证(screener 已粗筛,此处终判)
            rejected += 1
            continue
        fs = factors.score(d, f5_sub=f5_sub.get(sym), f5_raw=f5_raw.get(sym))
        f2 = fs["subs"].get("F2_trend")
        if f2 is not None and f2 >= f2_min and fs["score"] >= min_score:
            flags = []
            if (d.get("chg5_pct") or 0) > 40: flags.append("追高风险")
            if (d.get("rsi14") or 0) > 85: flags.append("过热")
            board.append({"symbol": sym, "trend_score": fs["score"], "trend_why": fs["why"], "subs": fs["subs"],
                          "price": d.get("price"), "chg5_pct": d.get("chg5_pct"), "chg10_pct": d.get("chg10_pct"),
                          "up5": d.get("up5"), "rsi14": d.get("rsi14"), "vol_x20": d.get("vol_x20"),
                          "adv20_musd": round((d.get("adv20_usd") or 0) / 1e6, 1), "flags": flags,
                          "asof": d.get("last_bar_date") or key})
        else:
            rejected += 1
    board.sort(key=lambda p: (-p["trend_score"], -(p["adv20_musd"] or 0), -(p["chg5_pct"] or 0)))
    board = board[:_TREND_CAP]
    print("[scout] 趋势榜键 %s:快照 %d/%d 末根=键日(覆盖 %.0f%%)" % (key, dated, len(snaps), coverage * 100))
    if coverage >= 0.5:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            json.dump({"key": key, "universe_n": len(universe), "rejected_n": rejected, "coverage": round(coverage, 3), "board": board},
                      open(path, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception:
            pass
    else:
        print("[scout] 趋势榜:当日 EOD 覆盖不足 50%%(FMP 未发布?),本次不落盘,下一班重算")
        fetchers._log_skip("trend_board", key, "当日 EOD 覆盖 %.0f%% <50%%,未落盘" % (coverage * 100))
    return board, len(universe), rejected


_POOL_CAP = 12


def candidate_pool(cross, view="swing"):
    """引擎候选池(v3.26,Lyra 2026-08-24:"冒烟测试的结果就没有到 Top Mover 榜?"):
    此前六眼(movers/最活跃/热簇/同频簇/连涨/自选)只作"参考"喂 DS,S1 由 DS 自由挑——
    8-24 财报班挑了热簇里 +1.77% 的 PATH 做 10 分钟 0DTE,BMNR(最活跃+🔥团)没进卡。
    现改确定性:宇宙=六眼并集 → 逐票实测(quote_layer 缓存)→ 硬地板(price/20 日成交额)→
    透明计分(每分一眼可查)→ 排序 cap 12。S1 只能从池内取,池前三必须逐票评估。
    计分(整数,score_why 逐项落 json):最活跃榜且当日收涨 +3(钱的直接测量;未收涨只 +1 并标"当日未收涨")/
    🔥同频团成员 +2 / 🔥热簇成员 +1 / 异动榜 +1 / 当日 +2%~+20% +2,(0,2%) +1,>20% +2 并标"追高风险" /
    连涨榜 +1 / 距 52 周高 <5% +1 / close_loc≥0.7 +1 / vol_x20≥1.5 +1 / 自选 +1;
    rsi14>75 只标"过热"不扣分(机器不藏强票)。同分按 20 日成交额降序(流动性优先),再按当日涨幅。
    可证伪:宇宙全不过地板→池空且筛除逐票有条款;无读数票不进池;收跌的最活跃巨头不占前排。"""
    eyes = {}

    def see(sym, tag):
        s = str(sym or "").upper()
        if re.fullmatch(r"[A-Z]{1,5}", s):
            eyes.setdefault(s, set()).add(tag)

    for x in (cross.get("market_movers") or []):
        if isinstance(x, dict) and x.get("side") == "gainers":
            see(x.get("symbol"), "异动")
    for x in (cross.get("most_active") or []):
        if isinstance(x, dict):
            see(x.get("symbol"), "最活跃")
    for c in (cross.get("comove") or []):
        if c.get("hot"):
            for mm in (c.get("members") or []):
                see(mm.get("symbol"), "同频🔥")
    for t in (cross.get("theme_heat") or []):
        if t.get("hot"):
            for mm in (t.get("members") or []):
                see(mm.get("symbol"), "热簇🔥")
    for s in (cross.get("streak_board") or []):
        see(s, "连涨")
    for x in (cross.get("watchlist") or []):
        see(x.get("symbol") if isinstance(x, dict) else x, "自选")
    for t in (cross.get("trend_board") or []):      # v3.28 第七只眼:自算趋势榜(BMNR 案)
        see(t.get("symbol") if isinstance(t, dict) else t, "趋势🔥")
    universe = sorted(eyes)
    if not universe:
        return [], [], 0
    snaps = fetchers.quote_layer_snapshot(universe, with_rsi=True)
    # v3.26.1(Lyra 2026-08-24:"不可以进池…IV 200% & IV 你选哪个"):ETF 硬排——最活跃榜常年
    # 被 IBIT/BITO/TSLL/SOXL 占位,BMNR/ASST/CRCL 型高 IV 单票被挤出;判据=profile isEtf/isFund
    # (同一 profile 端点,industry_lookup 终身缓存);类型未证(profile 无回包/无该键)同样不入,响亮
    ind = fetchers.industry_lookup(universe)
    pool, rejected = [], []
    edays = earnings_days_map(cross)
    # v3.29:先过准入(ETF/读数/地板),再对幸存者批量取 F5(Theta 快照,盘外为空→因子缺)
    survivors = []
    for s in universe:
        d = snaps.get(s)
        info = ind.get(s) if isinstance(ind.get(s), dict) else {}
        if info.get("is_etf") is False and d and not _floor_clause(d):
            survivors.append(s)
    f5_sub, f5_raw, f5_src = (f5_batch(snaps, survivors[:40]) if survivors else ({}, {}, "none"))
    for s in universe:
        d = snaps.get(s)
        tags = eyes[s]
        info = ind.get(s) if isinstance(ind.get(s), dict) else {}
        if d and d.get("mcap_b") is None and info.get("mktcap_b"):
            d["mcap_b"] = info["mktcap_b"]          # v3.29.1:quote 缺市值时用 profile 市值(F1 换手率不退成交额档)
        ie = info.get("is_etf")
        if ie is True:
            rejected.append({"symbol": s, "clause": "ETF 不入池(IV 结构不适合单腿 call)", "eyes": sorted(tags)})
            continue
        if ie is None:
            rejected.append({"symbol": s, "clause": "类型未证(profile 无 isEtf 回包),不入池", "eyes": sorted(tags)})
            continue
        if not d:
            rejected.append({"symbol": s, "clause": "quote_layer 无读数(FMP+Alpaca miss)",
                             "eyes": sorted(tags)})
            continue
        cl = _floor_clause(d)
        if cl:
            rejected.append({"symbol": s, "clause": cl, "price": d.get("price"), "eyes": sorted(tags)})
            continue
        chg = d.get("chg_pct")
        # v3.29:六因子核(factors.py),眼睛只决定谁进宇宙,不再各自加分——"来自哪张榜"不是经济因子
        fs = factors.score(d, days_to_earnings=edays.get(s), f5_sub=f5_sub.get(s), f5_raw=f5_raw.get(s), view=view)
        flags = []
        rsi = d.get("rsi14")
        if rsi is not None and rsi > 75:
            flags.append("RSI%.0f过热" % rsi)
        if (d.get("chg5_pct") or 0) > 40:
            flags.append("追高风险")
        if chg is not None and chg <= 0 and "最活跃" in tags:
            flags.append("当日未收涨")
        if fs["missing"]:
            flags.append("缺" + "/".join(k[:2] for k in fs["missing"]))
        elif f5_src.startswith("eod:"):
            flags.append("F5昨收")
        pool.append({"symbol": s, "score": fs["score"], "score_why": fs["why"], "subs": fs["subs"], "eyes": sorted(tags),
                     "price": d.get("price"), "chg_pct": chg,
                     "adv20_musd": round((d.get("adv20_usd") or 0) / 1e6, 1),
                     "mcap_b": d.get("mcap_b"), "rsi14": rsi, "close_loc": d.get("close_loc"),
                     "vol_x20": d.get("vol_x20"), "high52_dist_pct": d.get("high52_dist_pct"),
                     "chg5_pct": d.get("chg5_pct"), "days_to_earnings": edays.get(s), "flags": flags})
    # v3.29:入池最低分 POOL_MIN_SCORE(0–100 因子分,默认 45);低分票进筛除行带 score_why,不无痕
    min_score = int(os.getenv("POOL_MIN_SCORE", "45"))
    weak = [p for p in pool if p["score"] < min_score]
    for p in weak:
        rejected.append({"symbol": p["symbol"], "clause": "score %d<%d 入池最低分(%s)" % (p["score"], min_score, p["score_why"]),
                         "price": p["price"], "eyes": p["eyes"]})
    pool = [p for p in pool if p["score"] >= min_score]
    pool.sort(key=lambda p: (-p["score"], -(p["adv20_musd"] or 0), -(p["chg_pct"] or 0)))
    return pool[:_POOL_CAP], rejected, len(universe)


_TIME_RX = re.compile(r"(\d{1,2}):(\d{2})")


def normalize_pst_window(text, shift):
    """v3.29.3(8-26 中午班:卡写"入场窗(PST) 13:45-14:30 / 出场 15:30、15:50"——美股 13:00 PST 收盘,
    这些是 ET 数字贴了 PST 标签;prompt 说了 PST,DS 照写 ET,此前无代码校验):
    解析文本里的 HH:MM;若任一时刻 >13:00 → 判为 ET,整段 -3h 并标"(引擎:DS 写成 ET,已改)";
    改后仍有时刻落在 06:30–13:00 之外 → 返回 (text, "窗外");否则 (text, None)。空文本原样。"""
    if not text or not isinstance(text, str):
        return text, None
    times = [(int(h), int(m)) for h, m in _TIME_RX.findall(text)]
    if not times:
        return text, None
    note = None
    if any((h, m) > (13, 0) for h, m in times):
        def _shift(mo):
            h, m = int(mo.group(1)), int(mo.group(2))
            h2 = h - 3
            return "%02d:%02d" % (h2, m) if h2 >= 0 else mo.group(0)
        text = _TIME_RX.sub(_shift, text) + "(引擎:DS 写成 ET,已改 PST)"
        times = [(int(h), int(m)) for h, m in _TIME_RX.findall(text)]
        note = "tz_fixed"
    if any((h, m) < (6, 30) or (h, m) > (13, 0) for h, m in times):
        return text, "窗外"
    return text, note


def apply_quality_floor(data, shift, cross):
    """DS 点名过引擎地板(v3.26,代码闸,会改卡——此前三闸只盖章,PICS 无实测照出卡):
    ① 非空候选卡逐票实测(quote_layer memo,tape_check 已预热零增量)——price<地板 /
       20 日成交额<地板 / 无实测 = 卡作废:改 empty=true,empty_reason 带 ticker+条款,
       原卡整份存 _floor_killed,并列 ds["_floor_kills"];no_candidate_reason 追加逐票条款
       (规则 B"空槽唯一合法理由=质量地板"由此可审);
    ② S1 视野核对:ticker 不在 candidate_pool = 盖章 _pool_check="视野外点名"(不作废,
       机器不藏强票;DS 违反"S1 池内取"的事实留痕);
    ③ 财报班 S2/S4:ticker 必须在地板后的 amc_tonight/bmo_tomorrow/upcoming_earnings 名单内,
       否则作废(财报腿必须日历实证;名单外 = 训练记忆点名或已被地板筛除);
    ④ 财报班 S1/S3 = 明晨预排观察卡:note 前缀"明晨预排,不建仓"由引擎补齐(复盘按此不计命中)。
    对冲腿不过本闸(工具白名单另有规则)。"""
    if shift not in ("morning", "midday", "earnings") or not isinstance(data, dict):
        return data
    cands = data.get("candidates") or []
    pool_syms = {p.get("symbol") for p in (cross.get("candidate_pool") or []) if isinstance(p, dict)}
    earn_syms = set()
    for k in ("amc_tonight", "bmo_tomorrow", "upcoming_earnings"):
        earn_syms |= {(x.get("symbol") if isinstance(x, dict) else x) for x in (cross.get(k) or [])}
    kills = []
    _grp_count = {}            # v3.31 同频团计数(本班内)
    live = [str(c.get("ticker") or "").upper() for c in cands
            if isinstance(c, dict) and not c.get("empty") and c.get("slot") in (1, 3)]
    ind = fetchers.industry_lookup([t for t in live if re.fullmatch(r"[A-Z]{1,5}", t)]) if live else {}
    for c in cands:
        if not isinstance(c, dict) or c.get("empty"):
            continue
        t = str(c.get("ticker") or "").upper()
        slot = c.get("slot")
        if not re.fullmatch(r"[A-Z]{1,5}", t):
            # v3.26.3(戌 8-24 抓:"PICS,TUYA,GRRR"逗号票绕过质量闸——闸只认单票,并一起就跳过):
            # 非单一代码一律作废,一卡一票
            clause = "非单一代码 '%s'(逗号票/格式错),一卡一票,整卡作废" % t[:30]
            kills.append({"slot": slot, "ticker": t[:30], "clause": clause})
            killed = dict(c)
            c.clear()
            c.update({"slot": slot, "slot_name": killed.get("slot_name"), "empty": True,
                      "empty_reason": "引擎地板作废 %s:%s" % (t[:30], clause), "_floor_killed": killed})
            print("[scout] 引擎地板作废 S%s %s:%s" % (slot, t[:30], clause))
            continue
        d = (fetchers.quote_layer_snapshot([t], with_rsi=True) or {}).get(t)
        if not d:
            clause = "quote_layer 无读数(FMP+Alpaca miss)"
        else:
            clause = _floor_clause(d)
            c["floor_check"] = {"price": d.get("price"),
                                "adv20_musd": (round(d["adv20_usd"] / 1e6, 1) if d.get("adv20_usd") else None),
                                "verdict": clause or "过地板"}
        if clause is None and slot in (1, 3):   # v3.26.1:S1/S3 点名 ETF = 作废(池已硬排,DS 绕不过)
            ie = (ind.get(t) or {}).get("is_etf") if isinstance(ind.get(t), dict) else None
            if ie is True:
                clause = "ETF 不入候选(IV 结构不适合单腿 call;对冲/迁徙工具走 hedge 腿)"
        if clause is None and shift == "earnings" and slot in (2, 4) and t not in earn_syms:
            clause = "不在引擎财报名单(地板后 amc/bmo/run-up 三单),财报腿禁名单外点名"
        if clause is None and d:
            # v3.27(8-25 INTU 案:引擎量到 日-2.92% loc0.17 印在卡上,卡照发,盘后 -7%):
            # 方向与尾盘形态错配 = 作废。call:当日 ≤-1% 且 loc<0.5;put:当日 ≥+1% 且 loc>0.5。
            # 阈值 env TAPE_VETO_CHG / TAPE_VETO_LOC;盘中班用的是盘中读数,同判(动量不做逆势票)
            vc = float(os.getenv("TAPE_VETO_CHG", "1.0")); vl = float(os.getenv("TAPE_VETO_LOC", "0.5"))
            chg_, loc_ = d.get("chg_pct"), d.get("close_loc")
            dirn = str(c.get("direction") or "").lower()
            if chg_ is not None and loc_ is not None:
                if dirn == "call" and chg_ <= -vc and loc_ < vl:
                    clause = "形态错配:call 不做弱势收低票(日%+.2f%%, loc %.2f)" % (chg_, loc_)
                elif dirn == "put" and chg_ >= vc and loc_ > vl:
                    clause = "形态错配:put 不做强势收高票(日%+.2f%%, loc %.2f)" % (chg_, loc_)
        # v3.29.3 T+0 参与度闸:晨/午班 S1/S3 的 call 卡,盘中量 vol_x20 < T0_VOL_MIN(默认 0.8)= 没有人在买,
        # 0DTE 不建仓(8-26 TEM vol_x20 0.44、FUTU 0.62 案:卡自己写着"无放量需等信号",却仍是带入场窗的实卡)
        if clause is None and d and shift in ("morning", "midday") and slot in (1, 3) \
                and str(c.get("direction") or "").lower() == "call":
            vx_ = d.get("vol_x20")
            if vx_ is not None:
                # vol_x20 = 今日累计量 / 20 日均全日量,必须按班次时刻折算成"节奏":晨班 09:45 ET 只走了 15 分钟,
                # 0.15 已是放量;午班 13:40 ET 走了 64%。elapsed 取班次名义时刻,前 15 分钟占 15% 的 U 形近似
                elapsed_min = {"morning": 15, "midday": 250}.get(shift, 250)
                frac = min(1.0, 0.15 + 0.85 * (elapsed_min / 390.0))
                pace = vx_ / max(0.1, frac)
                pmin = float(os.getenv("T0_PACE_MIN", "0.8"))
                if ((cross.get("regime") or {}).get("event") or {}).get("event_day"):
                    pmin = max(pmin, float(os.getenv("T0_PACE_MIN_EVENT", "1.0")))   # 事件日:没有明确放量的 0DTE 一律只观察
                if pace < pmin:
                    clause = "无放量(vol_x20 %.2f,按班次时刻折算节奏 %.2f < %.1f):T+0 0DTE 不建仓,只观察" % (vx_, pace, pmin)
                c["_pace_check"] = {"vol_x20": vx_, "elapsed_frac": round(frac, 2), "pace": round(pace, 2)}
        # v3.29.3 时间窗:ET 数字贴 PST 标签 → 改;改后仍窗外 → 作废
        if clause is None:
            st_ = c.get("strategy") if isinstance(c.get("strategy"), dict) else {}
            bad_win = None
            for k_ in ("entry_window_pst", "exit_window_pst"):
                fixed, note_ = normalize_pst_window(st_.get(k_), shift)
                if fixed != st_.get(k_):
                    st_[k_] = fixed
                if note_ == "窗外":
                    bad_win = k_
            if bad_win:
                clause = "时间窗不在交易时段(%s=%s):作废" % (bad_win, st_.get(bad_win))
            # v3.31 事件时刻:入场窗与今日高影响发布/讲话时刻 ±15 分钟重叠 → 作废(周五 JH 10:00 ET 型)
            if clause is None:
                ev_t = (cross.get("regime") or {}).get("event") or {}
                win = _first_time(st_.get("entry_window_pst"))
                win_end = _last_time(st_.get("entry_window_pst")) or win
                for e_ in (ev_t.get("today_events") or []):
                    et_ = _first_time(str(e_.get("date") or ""))       # 日历时刻按 ET,转 PST
                    if not et_ or not win:
                        continue
                    et_pst = (et_[0] - 3, et_[1])
                    lo = (et_pst[0], et_pst[1] - 15) if et_pst[1] >= 15 else (et_pst[0] - 1, et_pst[1] + 45)
                    hi = (et_pst[0], et_pst[1] + 15) if et_pst[1] < 45 else (et_pst[0] + 1, et_pst[1] - 45)
                    if not (win_end < lo or win > hi):
                        clause = "入场窗撞事件时刻(%s %02d:%02d PST ±15min):作废" % (e_.get("event"), et_pst[0], et_pst[1])
                        break
        # v3.31 同团封顶:同一🔥同频团最多 COMOVE_CAP(默认 2)张实卡,超出按 rank 作废
        if clause is None:
            cap_ = int(os.getenv("COMOVE_CAP", "2"))
            grp_ = None
            for g_ in (cross.get("comove") or []):
                if t in {mm.get("symbol") for mm in (g_.get("members") or [])}:
                    grp_ = tuple(sorted(mm.get("symbol") for mm in (g_.get("members") or []) if mm.get("symbol")))
                    break
            if grp_:
                _grp_count.setdefault(grp_, 0)
                _grp_count[grp_] += 1
                if _grp_count[grp_] > cap_:
                    clause = "同频团超限(该团已 %d 张,上限 %d):一注不拆成多注" % (_grp_count[grp_] - 1, cap_)
        ev_ = (cross.get("regime") or {}).get("event") or {}
        if clause is None and ev_.get("event_day") and not c.get("empty"):
            st_ = c.get("strategy") if isinstance(c.get("strategy"), dict) else {}
            tag_ = "事件日(" + ";".join(ev_.get("why") or [])[:80] + "):"
            if not str(c.get("note") or "").startswith("事件日"):
                c["note"] = tag_ + str(c.get("note") or "")
            if shift == "earnings" and slot in (2, 4) and ev_.get("megacap_amc") and str(c.get("direction") or "").lower() == "call":
                c["_event_check"] = "巨头盘后同夜持仓:系统性 gap 风险,DS 无对冲腿则由 Lyra 拍"
        if clause is None and shift == "earnings" and slot in (2, 4) and str(c.get("direction") or "").lower() == "call":
            board = fmp_board_syms(cross)
            if t not in board:   # v3.27.1(Lyra 8-25:不在 FMP top mover 榜的不收)
                clause = ("不在当日榜(FMP 涨幅榜/最活跃收涨/自算趋势榜),财报 call 腿无资金确认"
                          + ("" if board else ";且本班三榜为空(源失败),不装数"))
        if clause:
            kills.append({"slot": slot, "ticker": t, "clause": clause})
            killed = dict(c)
            c.clear()
            c.update({"slot": slot, "slot_name": killed.get("slot_name"), "empty": True,
                      "empty_reason": "引擎地板作废 %s:%s" % (t, clause),
                      "_floor_killed": killed})
            print("[scout] 引擎地板作废 S%s %s:%s" % (slot, t, clause))
            continue
        if slot == 1 and pool_syms and t not in pool_syms:
            c["_pool_check"] = "视野外点名(不在引擎候选池,规则=S1 池内取)"
        if shift == "earnings" and slot in (1, 3):
            note = str(c.get("note") or "")
            if "明晨预排" not in note:
                c["note"] = ("明晨预排,不建仓;" + note) if note else "明晨预排,不建仓"
    if kills:
        data["_floor_kills"] = kills
        extra = "; ".join("%s(%s)" % (k["ticker"], k["clause"]) for k in kills)
        ncr = str(data.get("no_candidate_reason") or "")
        data["no_candidate_reason"] = (ncr + "; " if ncr else "") + "[引擎地板作废] " + extra
    return data


def _scout_bark(shift, today, ds):
    """班次 Bark 推送(戌 8-21 现场加,守恒回流重写:certifi 上下文替代 unverified)。
    推:班次+日期+非空卡数+候选 ticker+违例。DOCTOR_BARK_URL 未配置=静默跳过。"""
    url = os.getenv("DOCTOR_BARK_URL", "").strip().rstrip("/")
    if not url or not isinstance(ds, dict):
        return
    try:
        cands = ds.get("candidates") or []
        ne = [c for c in cands if not c.get("empty")]
        tickers = ",".join((c.get("ticker") or "?") for c in ne) or "无"
        vio = ds.get("_floor_violation") or []
        title = "[SCOUT] %s %s 非空卡%d" % (shift, today, len(ne))
        body = "候选:%s" % tickers + (";违例:%s" % "|".join(vio)[:200] if vio else "")
        import urllib.parse
        full = "%s/%s/%s?group=scout-brief" % (url, urllib.parse.quote(title), urllib.parse.quote(body))
        req = urllib.request.Request(full, method="GET")
        with urllib.request.urlopen(req, timeout=10, context=fetchers._ssl_context()) as r:
            r.read()
        print("[scout] 班次 bark 已推")
    except Exception as e:
        print("[scout] 班次 bark 失败(不阻塞):", str(e)[:120])


def _sight_watch_syms(cross):
    """全视野器官的 watch 汇入(复盘跟踪,不计命中)。"""
    syms = set()
    for t in (cross.get("theme_heat") or []):
        if t.get("hot"):
            syms |= {m["symbol"] for m in t.get("members", []) if m.get("symbol")}
    syms |= set(cross.get("streak_board") or [])
    for c in (cross.get("comove") or []):
        if c.get("hot"):
            syms |= {mm["symbol"] for mm in c.get("members", []) if mm.get("symbol")}
    return syms


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
        for k in ("amc_tonight", "earnings_movers", "bmo_tomorrow", "market_movers",
                  "most_active", "watchlist"):
            wset |= {((x.get("symbol") if isinstance(x, dict) else x) or "").upper()
                     for x in (eng.get(k) or [])}
        wset |= _sight_watch_syms(eng)   # 热主题成员+streak 榜进复盘 watch(v3.25.8)
        for l in (ds.get("candidates") or []):
            note_all = "%s %s" % (l.get("note") or "", (l.get("strategy") or {}).get("note") or "")
            if "AMC 初筛观察" in note_all or "明晨预排" in note_all:   # v3.26:财报班预排卡同判
                w0 = str(l.get("ticker") or "").upper()
                if re.fullmatch(r"[A-Z]{1,5}", w0):
                    wset.add(w0)          # 初筛观察卡:进 watch,不进命中账(v3.25.6)
                continue
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
        rich.append(_leg_tier({"symbol": sym, "rsi14": (r or {}).get("rsi14"),
                     "chg5_pct": (r or {}).get("chg5_pct"), "chg_pct": (r or {}).get("chg_pct"),
                     "price": (r or {}).get("price"), "adv20_usd": (r or {}).get("adv20_usd"),
                     "close_loc": (r or {}).get("close_loc"), "vol_x20": (r or {}).get("vol_x20"),
                     "chg10_pct": (r or {}).get("chg10_pct"), "up5": (r or {}).get("up5"),
                     "dist_high20_pct": (r or {}).get("dist_high20_pct"), "mcap_b": (r or {}).get("mcap_b"),
                     "days_out": 0}))
    return _sort_earn(rich)   # v3.27:尾盘形态分排序,不按市值


def _leg_tier(row):
    """伏击名单档位标注(v3.25.3):run-up(chg5>0)/oversold(chg5<-2,WOLF/JBSS 型)/flat;
    dk_risk=双杀风险位(chg5>15 或 rsi>75)——v3.25.3 起不再机械禁入,亮牌交 Lyra 拍板。
    v3.27(2026-08-25 INTU 案:名单按市值序,DS 点了当日 -2.92%、loc 0.17 收在最低的 INTU 做持过财报 call,
    盘后 -7%;同名单 SMTC 当日 +5.4% 收高没被点)——名单改按 earn_score 排,尾盘形态是财报腿的全部论据:
    收高位 loc≥0.7 +2 / loc<0.3 -2;当日 ≥+1% +1 / ≤-1% -2;5 日 +2~+15% +1 / <-5% -1;
    rsi14 50-70 +1 / >75 -1 / <40 -1;放量 vol_x20≥1.3 且当日收涨 +1;dk_risk -1。earn_why 逐项落 json。"""
    c5, rsi = row.get("chg5_pct"), row.get("rsi14")
    row["tier"] = ("oversold" if (c5 is not None and c5 < -2)
                   else ("run-up" if (c5 is not None and c5 > 0) else "flat"))
    row["dk_risk"] = bool((c5 is not None and c5 > 15) or (rsi is not None and rsi > 75))
    # v3.29:财报名单同一因子核(F4 = days_out;当日 AMC = 0 只准预排);0–100
    fs = factors.score(row, days_to_earnings=row.get("days_out"))
    row["earn_score"], row["earn_why"], row["subs"] = fs["score"], fs["why"], fs["subs"]
    return row


def _sort_earn(rows):
    """财报名单排序:earn_score 降序,同分按 20 日成交额降序(v3.27,替代市值序)。"""
    return sorted(rows, key=lambda x: (-(x.get("earn_score") if x.get("earn_score") is not None else -99),
                                       -(x.get("adv20_usd") or 0)))


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
        rich.append(_leg_tier({"symbol": sym, "rsi14": (r or {}).get("rsi14"),
                     "chg5_pct": (r or {}).get("chg5_pct"), "chg_pct": (r or {}).get("chg_pct"),
                     "price": (r or {}).get("price"), "adv20_usd": (r or {}).get("adv20_usd"),
                     "close_loc": (r or {}).get("close_loc"), "vol_x20": (r or {}).get("vol_x20"),
                     "chg10_pct": (r or {}).get("chg10_pct"), "up5": (r or {}).get("up5"),
                     "dist_high20_pct": (r or {}).get("dist_high20_pct"), "mcap_b": (r or {}).get("mcap_b"),
                     "days_out": 1}))
    return _sort_earn(rich)   # v3.27:尾盘形态分排序,不按市值


def upcoming_earnings(payload, today):
    """确定性名单:未来 1-8 个交易日财报(run-up 窗)——S2a 腿的引擎供数。
    EL 案根修第二半:EL 08-15 起就在日历(V2 取证),但该腿此前只有 prompt 规则、
    没有引擎名单,数百行原始日历被 _slim_raw 预算裁剪,DS 结构性看不见。
    v3.26.2(NVDA 周案,Lyra"财报再好好测"):旧版整日剔除次一交易日——次日 BMO 归 bmo_tomorrow
    没错,但次日 AMC 票(周二班看周三盘后的 NVDA)三张名单都不在,财报班结构性看不见;
    现只剔除次日 pre-market,次日 AMC/未注明作 1 日 run-up 入名单,days_out 逐票标注
    (1 = 明日盘后出,只有一个交易日的 run-up 窗,公布前必须离场)。
    市值降序 cap 12,全票附实测读数(付费档+缓存)。"""
    d = datetime.date.fromisoformat(today)
    win, step = {}, d
    for k in range(1, 9):
        step = datetime.date.fromisoformat(_next_trading_day(step.isoformat()))
        win[step.isoformat()] = k
    nd = _next_trading_day(today)
    rows = []
    for src_ in payload.get("results", payload.get("sources", [])):
        if src_.get("source") == "earnings_calendar":
            for it in src_.get("items", []):
                sym = (it.get("symbol") or "").upper()
                dt, when = it.get("date"), (it.get("when") or "")
                if dt in win and re.fullmatch(r"[A-Z]{1,5}", sym):
                    if dt == nd and "pre-market" in when:
                        continue                   # 次日 BMO 归 bmo_tomorrow 腿
                    mc = fetchers._parse_money(it.get("marketCap")) or 0
                    rows.append({"symbol": sym, "date": dt, "when": when,
                                 "days_out": win[dt], "_mc": mc})
    # v3.26.2:近窗(days_out≤2,可执行的 run-up 窗)全保留,远窗(3-8 日)按市值另取 6——旧版整体
    # 按市值 cap 12,远窗巨头把明日盘后的中盘(OKTA 型)挤出名单;反向也不许:近窗塞满时远窗巨头
    # (BABA d4 型)整段消失。两窗各自有座位;地板在 floor_earnings_lists 再筛
    rows.sort(key=lambda x: (x["days_out"] > 2, -x["_mc"]))
    seen, out, far = set(), [], 0
    for x in rows:
        if x["symbol"] in seen:
            continue
        if x["days_out"] > 2:
            if far >= 6:
                continue
            far += 1
        seen.add(x["symbol"])
        out.append({k: v for k, v in x.items() if k != "_mc"})
    for x in out:   # v3.26:全票实测(付费档+缓存;地板要每票有价格/成交额读数)
        r = fetchers._stooq_daily(x["symbol"].lower() + ".us", x["symbol"], "upcoming_earnings")
        x.update({"rsi14": (r or {}).get("rsi14"), "chg5_pct": (r or {}).get("chg5_pct"),
                  "price": (r or {}).get("price"), "adv20_usd": (r or {}).get("adv20_usd"),
                  "chg_pct": (r or {}).get("chg_pct"), "close_loc": (r or {}).get("close_loc"),
                  "vol_x20": (r or {}).get("vol_x20"), "chg10_pct": (r or {}).get("chg10_pct"),
                  "up5": (r or {}).get("up5"), "dist_high20_pct": (r or {}).get("dist_high20_pct"),
                  "mcap_b": (r or {}).get("mcap_b")})
        _leg_tier(x)
    return _sort_earn(out)    # v3.27:近窗内按尾盘形态分排(days_out 仍逐票带)


def theme_heat(payload):
    """热簇·数据自聚(2026-08-21 二版,Lyra:禁写死范围——"万一下周热点不在这里了呢"。
    一版手写五主题表已拆除。热点由数据自己聚:
    宇宙 = 当日 movers 涨侧 ∪ most_active(自带实测涨跌)→ FMP profile 行业标签分组
    (industry_lookup 终身缓存)→ 同行业 ≥2 票且平均涨 ≥2%,或 ≥3 票且 ≥1.2% = 热簇。
    下周热点换到稀土/航运/生科,簇自己浮出来,零人工维护。cross 键名沿用 theme_heat。"""
    # 读法对齐 fetchers 真实落盘形状(顶层 items;movers 条目带 side)——
    # 2026-08-21 端到端首跑抓获:初版按想象形状读 data.gainers,真管线拿空。
    # 2026-08-24 现场首晚案:最活跃榜失败时簇宇宙只剩 movers 微盘尖峰,壳公司
    # +355% 挂🔥冒充"钱在流入"。修:①movers 侧 price≥5 才入簇宇宙(壳票出局,
    # movers 渲染行本身不受影响);②🔥资格必须资金确认——簇内至少一名成员在
    # 最活跃榜(成交额=钱的直接测量);最活跃榜空/失败=当班无簇可获🔥,不装。
    rows, actives_set = {}, set()
    for r in (payload.get("results") or []):
        if not r.get("ok"):
            continue
        if r.get("source") == "market_movers":
            for x in (r.get("items") or []):
                if (x.get("side") == "gainers" and x.get("symbol")
                        and x.get("chg_pct") is not None and (x.get("price") or 0) >= 5):
                    rows[x["symbol"]] = float(x["chg_pct"])
        elif r.get("source") == "most_active":
            for x in (r.get("items") or []):
                if x.get("symbol") and x.get("chg_pct") is not None:
                    rows.setdefault(x["symbol"], float(x["chg_pct"]))
                    actives_set.add(x["symbol"])
    if not rows:
        return []
    ind = fetchers.industry_lookup(sorted(rows))
    groups = {}
    for sym, chg in rows.items():
        tag = (ind.get(sym) or {}).get("industry") or (ind.get(sym) or {}).get("sector")
        if not tag:
            continue
        groups.setdefault(tag, []).append({"symbol": sym, "chg_pct": round(chg, 2)})
    out = []
    for tag, members in groups.items():
        chgs = [mm["chg_pct"] for mm in members]
        avg = round(sum(chgs) / len(chgs), 2)
        n = len(members)
        money = any(mm["symbol"] in actives_set for mm in members)
        out.append({"theme": tag, "n": n, "avg_chg": avg,
                    "up_ratio": round(sum(1 for c in chgs if c > 0) / n, 2),
                    "hot": bool(money and ((n >= 2 and avg >= 2.0) or (n >= 3 and avg >= 1.2))),
                    "money_confirmed": money,
                    "members": sorted(members, key=lambda mm: mm["chg_pct"], reverse=True)})
    out.sort(key=lambda t: (t["hot"], t["n"], t["avg_chg"]), reverse=True)
    return out[:12]


def _pearson(a, b):
    n = min(len(a), len(b))
    if n < 6:
        return None
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a) ** 0.5
    vb = sum((y - mb) ** 2 for y in b) ** 0.5
    if va == 0 or vb == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (va * vb)


def _max_cliques(nodes, edges):
    """Bron–Kerbosch(带枢轴):极大团枚举。宇宙 ~40 节点,规模无忧。"""
    out = []
    def bk(R, P, X):
        if not P and not X:
            if len(R) >= 3:
                out.append(set(R))
            return
        pivot = max(P | X, key=lambda v: len(edges[v] & P), default=None)
        for v in list(P - (edges[pivot] if pivot else set())):
            bk(R | {v}, P & edges[v], X & edges[v])
            P = P - {v}
            X = X | {v}
    bk(set(), set(nodes), set())
    return out


def comove_clusters(payload):
    """同频簇(2026-08-24 四版,三路云审后收刀:GLM 主刀+DS 语义+Kimi 堵连坐)。
    立法:"这些票在一起动"=两两都在动,不是"在同一个朋友圈"(DS 语)——
    连通分量是传递闭包,FSTB 能靠中间人挂上 NVDA,已废。现定义:
    · 簇 = 极大团(clique):任意两成员 10 日日收益 ρ≥0.7,贪心取不相交团;
    · cohesion = 团内全对全 ρ 均值(团定义下无隐藏对,不再虚报);
    · money = ≥2 名成员在最活跃榜(单只常驻巨头不再一人连坐确认全簇,Kimi 案);
    · hot = money 且 当日中位数 chg≥1.5% 且 ≥60% 成员 chg≥1.5%(均值废,
      FSTB +2021% 单票拉爆均值案);
    · members 全量入 json,渲染截断必须响亮标 k/n(展示层禁撒谎)。
    可证伪不变:链式不成簇、无共振输出空、不相关同 sector 被拒。"""
    rows, actives_set = {}, set()
    for r in (payload.get("results") or []):
        if not r.get("ok"):
            continue
        if r.get("source") == "market_movers":
            for x in (r.get("items") or []):
                if (x.get("side") == "gainers" and x.get("symbol")
                        and x.get("chg_pct") is not None and (x.get("price") or 0) >= 5):
                    rows[x["symbol"]] = float(x["chg_pct"])
        elif r.get("source") == "most_active":
            for x in (r.get("items") or []):
                if x.get("symbol") and x.get("chg_pct") is not None:
                    rows.setdefault(x["symbol"], float(x["chg_pct"]))
                    actives_set.add(x["symbol"])
    if len(rows) < 3:
        return []
    rets, rho = {}, {}
    for sym in sorted(rows):
        try:
            closes = fetchers.quote_layer_bars(sym, limit=13) or []
        except Exception:
            closes = []
        if len(closes) >= 8:
            rets[sym] = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))][-10:]
    syms = sorted(rets)
    edges = {s: set() for s in syms}
    for i, a in enumerate(syms):
        for b in syms[i + 1:]:
            r_ = _pearson(rets[a], rets[b])
            rho[(a, b)] = r_
            if r_ is not None and r_ >= 0.7:
                edges[a].add(b)
                edges[b].add(a)
    cliques = _max_cliques(syms, edges)
    def _coh(c):
        cs = sorted(c)
        ps = [rho.get((a, b)) or rho.get((b, a)) or 0
              for i2, a in enumerate(cs) for b in cs[i2 + 1:]]
        return round(sum(ps) / len(ps), 2) if ps else None
    cliques.sort(key=lambda c: (len(c), _coh(c) or 0), reverse=True)
    used, clusters = set(), []
    for c in cliques:
        if c & used:
            continue
        used |= c
        members = sorted(({"symbol": x, "chg_pct": rows[x]} for x in c),
                         key=lambda mm: mm["chg_pct"], reverse=True)
        chgs = sorted(mm["chg_pct"] for mm in members)
        med = chgs[len(chgs) // 2] if len(chgs) % 2 else (chgs[len(chgs) // 2 - 1] + chgs[len(chgs) // 2]) / 2
        share = sum(1 for v in chgs if v >= 1.5) / len(chgs)
        money = sum(1 for mm in members if mm["symbol"] in actives_set) >= 2
        ind = fetchers.industry_lookup(sorted(c))
        clusters.append({"n": len(c), "cohesion": _coh(c),
                         "avg_chg": round(sum(chgs) / len(chgs), 2),
                         "med_chg": round(med, 2), "share_up": round(share, 2),
                         "money": money,
                         "hot": bool(money and med >= 1.5 and share >= 0.6),
                         "industries": sorted({((ind.get(x) or {}).get("industry") or "?") for x in c}),
                         "members": members})
    clusters.sort(key=lambda c: (c["hot"], c["n"], c["med_chg"]), reverse=True)
    return clusters[:3]


def most_active_health(payload):
    """最活跃榜健康态(2026-08-24 立):失败/空必须在渲染里响亮报出,禁静默——
    资金确认腿断了要让人一眼看见,不能让簇段拿垃圾冒充信号。"""
    for r in (payload.get("results") or []):
        if r.get("source") == "most_active":
            if r.get("ok") and (r.get("items") or []):
                return None
            return r.get("error") or "ok 但空列表"
    return "raw 中无 most_active 源(爬虫未跑?)"


def most_active(payload):
    """最活跃榜提取(爬虫#13):热资金直测,cap 24。读法=fetchers 真实落盘顶层 items。"""
    for r in (payload.get("results") or []):
        if r.get("source") == "most_active" and r.get("ok"):
            return (r.get("items") or [])[:24]
    return []


def update_streaks(today, movers_rows, active_rows):
    """连涨/连续上榜账本:movers 榜抓尖峰抓不到三日稳步流(8-21 案),
    落盘每日榜单符号,近 3 日出现 ≥2 次者=streak 榜,补趋势盲区。"""
    p = os.path.join(OUT, "state", "movers_history.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        hist = json.load(open(p, encoding="utf-8"))
    except Exception:
        hist = {}
    hist[today] = sorted({(m.get("symbol") or "").upper()
                          for m in (movers_rows or []) + (active_rows or [])
                          if (m.get("chg_pct") or 0) > 0 and m.get("symbol")})
    hist = {k: hist[k] for k in sorted(hist)[-10:]}
    try:
        json.dump(hist, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception as e:
        print("[scout] streak 账本写盘失败(不阻塞):", str(e)[:100])
    cnt = {}
    for d in sorted(hist)[-3:]:
        for s in hist.get(d, []):
            cnt[s] = cnt.get(s, 0) + 1
    return sorted([s for s, c in cnt.items() if c >= 2])


def load_watchlist():
    """交易员自选名单(可选附加层,非视野主体):ROOT/watchlist.txt 一行一票。"""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.txt")
    if not os.path.exists(p):
        return []
    try:
        return [l.strip().upper() for l in open(p, encoding="utf-8")
                if l.strip() and not l.strip().startswith("#")][:30]
    except Exception:
        return []


def market_movers(payload):
    """全市场异动榜提取(v3.25.2,Lyra 拍板 2026-08-20):raw market_movers 源 →
    |chg| 降序 cap 24。所有班消费:引擎行渲染 + DS prompt 申明 + 晚班复盘 watch 并入。
    MRNA/TEM/比特币板块型非财报大涨从此在数据层与每班视野内。"""
    rows = []
    for src_ in payload.get("results", payload.get("sources", [])):
        if src_.get("source") == "market_movers":
            for it in (src_.get("items") or []):
                if it.get("symbol") and it.get("chg_pct") is not None:
                    rows.append({"symbol": it["symbol"], "side": it.get("side"),
                                 "chg_pct": it["chg_pct"], "price": it.get("price"),
                                 "name": it.get("name")})
    rows.sort(key=lambda x: -abs(x["chg_pct"]))
    seen, out = set(), []
    for x in rows:
        if x["symbol"] in seen:
            continue
        seen.add(x["symbol"])
        out.append(x)
        if len(out) >= 24:
            break
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


def afterhours_symbols(cross, today):
    """盘后查询名单(v3.25.2 COTY 案,v3.26.3 改地板后):amc_tonight 幸存者 ∪ 当日各班非空候选腿;
    "明晨预排"观察卡与 AMC 初筛卡不查(不是持仓腿)。"""
    syms = {(x["symbol"] if isinstance(x, dict) else x) for x in (cross.get("amc_tonight") or [])}
    for sh in ("morning", "midday", "earnings"):
        p_ = os.path.join(OUT, "briefs", "%s-%s.json" % (today, sh))
        if not os.path.exists(p_):
            continue
        try:
            for c in ((json.load(open(p_, encoding="utf-8")) or {}).get("ds") or {}).get("candidates") or []:
                t_ = str(c.get("ticker") or "").upper()
                note = "%s %s" % (c.get("note") or "", (c.get("strategy") or {}).get("note") or "")
                if t_ and not c.get("empty") and re.fullmatch(r"[A-Z]{1,5}", t_) \
                        and "明晨预排" not in note and "AMC 初筛观察" not in note:
                    syms.add(t_)
        except Exception:
            pass
    return {x for x in syms if x and re.fullmatch(r"[A-Z]{1,5}", str(x))}


def afterhours_health(ah, syms, skips):
    """盘后读数健康态(v3.26.3,戌 8-24 抓 amc_results 仍空):出数 k/n + 原因分布——
    21:00 PST 晚班 = 00:00 ET,Nasdaq 盘后 secondaryData 常已收(8-20 压库项),空要响亮报原因。"""
    items = (ah or {}).get("items") or []
    got = sum(1 for i in items if i.get("ah_chg_pct") is not None)
    reasons = {}
    for i in items:   # 端点有回包但盘后字段空(secondaryData=null)的票不进 skips,从条目自身判
        if i.get("ah_chg_pct") is None:
            key = "no secondaryData" if i.get("ah_last") is None else ("双算冲突" if i.get("ah_conflict") else "盘后字段空")
            reasons[key] = reasons.get(key, 0) + 1
    for k in skips or []:
        if k.get("source") == "afterhours":
            r = str(k.get("reason") or "")
            key = ("no secondaryData" if "secondaryData" in r else "双算冲突" if "冲突" in r
                   else "HTTP/网络" if any(w in r for w in ("HTTP", "URL", "urlopen", "SSL", "timed", "Errno")) else r[:30])
            reasons[key] = reasons.get(key, 0) + 1
    if not (ah or {}).get("ok", True) and (ah or {}).get("error"):
        reasons.setdefault("源级失败", 0); reasons["源级失败"] = 1
    txt = "实时 %d/%d 出数" % (got, len(syms))
    if reasons:
        txt += ";缺数原因:" + ",".join("%s×%d" % kv for kv in sorted(reasons.items(), key=lambda kv: -kv[1]))
    if got == 0:
        txt += "(时点 00:00 ET 已过盘后窗——用 --mode afterhours 16:45 PST 快照可补,见 README)"
    return txt


def _afterhours_snapshot_path(today):
    return os.path.join(OUT, "state", "afterhours-%s.json" % today)


def load_afterhours_snapshot(today):
    """晚班优先吃 16:45 PST 盘后快照(--mode afterhours 落盘);无则 None(回落实时取)。"""
    try:
        doc = json.load(open(_afterhours_snapshot_path(today), encoding="utf-8"))
        if isinstance(doc, dict) and isinstance(doc.get("items"), list):
            return doc
    except Exception:
        pass
    return None


def run_afterhours_snapshot(payload, today):
    """--mode afterhours(v3.26.3):16:45 PST(=19:45 ET,Nasdaq 盘后窗内)取 amc_tonight(地板后)∪
    当日候选腿的盘后读数落 state/afterhours-日.json,21:00 晚班优先消费。不调 DS,不写简报,不进账本。
    plist 模板 com.grid.afterhours-snap.plist.new 随包,是否 load 由 Lyra 拍板。"""
    cross = {"amc_tonight": amc_tonight(payload, today)}
    floor_earnings_lists(cross)
    syms = afterhours_symbols(cross, today)
    if not syms:
        print("[scout] afterhours 快照:今日无盘后名单"); return None
    n0 = len(fetchers.SKIPS)
    ah = fetchers.fetch_afterhours(sorted(syms)[:24])
    doc = {"asof": datetime.datetime.now().astimezone().isoformat(), "ok": bool(ah.get("ok")),
           "error": ah.get("error"), "symbols": sorted(syms), "items": ah.get("items") or [],
           "skips": fetchers.SKIPS[n0:], "health": afterhours_health(ah, syms, fetchers.SKIPS[n0:])}
    os.makedirs(os.path.dirname(_afterhours_snapshot_path(today)), exist_ok=True)
    json.dump(doc, open(_afterhours_snapshot_path(today), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("[scout] afterhours 快照落盘 %s:%s" % (_afterhours_snapshot_path(today), doc["health"]))
    # v3.29.1:F5 昨收缓存——当日快照 19:45 ET 仍在(文档:午夜 ET 重置),取 候选并集 的 ATM call γ/|θ| 落盘,
    # 次晨盘前池与晚班趋势榜回退用(标 F5昨收)。并集 = 盘后名单 ∪ 当日趋势榜 ∪ 当日三班候选池
    f5_syms = set(syms)
    try:
        tb_doc = json.load(open(os.path.join(OUT, "state", "trend_board-%s.json" % today), encoding="utf-8"))
        f5_syms |= {t["symbol"] for t in (tb_doc.get("board") or [])}
    except Exception:
        pass
    for shift_ in ("morning", "midday", "earnings"):
        try:
            bd = json.load(open(os.path.join(OUT, "briefs", "%s-%s.json" % (today, shift_)), encoding="utf-8"))
            f5_syms |= {p["symbol"] for p in ((bd.get("_engine") or {}).get("candidate_pool") or [])}
        except Exception:
            pass
    f5_syms = sorted(f5_syms)[:80]
    snaps5 = fetchers.quote_layer_snapshot(f5_syms, with_rsi=False) if f5_syms else {}
    _, raws5, _ = f5_batch(snaps5, f5_syms, allow_afterhours=True)
    f5_persist(today, raws5)
    print("[scout] F5 昨收缓存 %s:%d/%d 票出数" % (_f5_cache_path(today), sum(1 for v in raws5.values() if v is not None), len(f5_syms)))
    return doc


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


def glm_morning_land_or_die(date):
    """晨报公开落盘硬闸。DS json/html/md 只是半成品;无 GLM 编译章禁止当作已落盘。
    调用 scripts/scout_land_option.py(写 morning-final.md + OPTION emit)。失败非零退出。"""
    here = os.path.dirname(os.path.abspath(__file__))
    script = os.path.normpath(os.path.join(here, "..", "scripts", "scout_land_option.py"))
    if not os.path.isfile(script):
        raise SystemExit("晨报 GLM land 脚本缺失:%s——禁止把 DS 直出当落盘" % script)
    print("[scout] 晨报 GLM land 硬闸 →", script, date)
    r = subprocess.run([sys.executable, script, "--date", date], cwd=here)
    if r.returncode != 0:
        raise SystemExit("晨报 GLM land 失败 exit=%s——禁止把 DS 直出当落盘" % r.returncode)
    final = os.path.join(OUT, "briefs", "%s-morning-final.md" % date)
    if not os.path.isfile(final):
        raise SystemExit("晨报缺 morning-final.md——禁止落盘")
    txt = open(final, encoding="utf-8").read()
    if "review_origin=glm52_cloud" not in txt:
        raise SystemExit("晨报 final 无 glm52_cloud 编译章——禁止落盘")
    print("[scout] 晨报 GLM 编译已落盘:", final)


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
    空回/网关失败 = 禁止落盘(晨报/晚报必须 GLM 编译后才算落地)。
    v3.25.2 回流 b286083:走 WB(8515 b11)签名转发,body 带 task,回包取 final。"""
    scout_expanded_memory_node = "scout-review-%s" % date
    # v3.26.3(戌 8-24 抓:包装径 9000 字撞网关 8000 字闸,EXPANDED 直接失败):任务字数 env
    # EXPANDED_TASK_CHARS 默认 8000;网关拒绝时把 HTTP 码+正文前 200 字打出来,不再只有"失败"
    _cap = int(os.getenv("EXPANDED_TASK_CHARS", "8000"))
    body = {"lane": "scout_evening",
            "cloud_backend": "glm52_cloud",
            "memory_node": scout_expanded_memory_node,
            "persist": True,
            "task": (final_md or "")[:_cap],
            "messages": [
                {"role": "system", "content": "Scout 晚报 EXPANDED review。中文 Markdown,不编报价。"},
                {"role": "user", "content": (final_md or "")[:_cap]},
            ]}
    try:
        blob = json.dumps(body, ensure_ascii=False).encode()
        req = urllib.request.Request(WB + "/gateway/task/expanded", data=blob,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=300, context=fetchers._ssl_context()) as r:
            res = json.loads(r.read().decode())
        txt = (res.get("final") or res.get("content") or "").strip()
        if not txt:
            raise SystemExit("[scout] EXPANDED-GLM review 空回——晚报禁止落盘")
        p = os.path.join(OUT, "briefs", "%s-evening-glm-review.md" % date)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w", encoding="utf-8").write(txt)
        ts = fetchers.now_et().isoformat(timespec="seconds")
        pf = os.path.join(OUT, "briefs", "%s-evening-final.md" % date)
        open(pf, "w", encoding="utf-8").write(
            "# Scout 晚报复盘 · %s\n\n> review_origin=glm52_cloud · review_ts=%s\n\n%s\n"
            % (date, ts, txt))
        print("[scout] EXPANDED-GLM review 落盘:", p, "+", pf)
        sys_content = "Scout 晚报 EXPANDED review。中文 Markdown,不编报价。"
        store_msgs = [
            {"role": "user", "content": sys_content + "\n\n" + (final_md or "")[:_cap], "surface": "grid-app"},
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
            print("[scout] EXPANDED-GLM review store 同步失败(编译已落盘,store 镜像不挡):", str(se)[:120])
        return txt
    except SystemExit:
        raise
    except urllib.error.HTTPError as e:
        try:
            _body = e.read().decode(errors="replace")[:200]
        except Exception:
            _body = ""
        raise SystemExit("[scout] EXPANDED-GLM review 失败——晚报禁止落盘:HTTP %s %s | task %d 字(闸 %d) | 正文:%s"
                         % (e.code, e.reason, len((final_md or "")[:_cap]), _cap, _body))
    except Exception as e:
        raise SystemExit("[scout] EXPANDED-GLM review 失败——晚报禁止落盘:%s" % str(e)[:160])


# ———— Grid 纪律降噪层(2026-08-08 入库;定义在 v3.25.2 出包时丢失、带病五版,
# 2026-08-23 现场晚报 NameError 后补回 v3.25.0 原文——verify 自此加全局名可解析检查)————
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
            ("地板实测(引擎)", (("$%s · 20日成交额 $%sM · %s" % (fc.get("price"), fc.get("adv20_musd"), fc.get("verdict")))
                            if (fc := (c.get("floor_check") or {})) else None)),
            ("视野核对(引擎)", c.get("_pool_check")),
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
    kills = data.get("_floor_kills") or []
    if kills:   # v3.26:DS 点名被引擎地板作废——票与条款一行可审,不无痕
        out.append('<section><h2>二·附 · 引擎地板作废(DS 点名未过地板,不出卡)</h2><div class="card">%s</div></section>'
                   % "".join('<div class="kv"><b>S%s %s</b><span>%s</span></div>'
                             % (_esc(k.get("slot")), _esc(k.get("ticker")), _esc(k.get("clause"))) for k in kills))
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
    if cross.get("factor_report_line"):   # v3.31 反馈回路
        rows.append(("因子表现(近 20 日,IC=子分与结果秩相关;权重改动看这行拍)", cross["factor_report_line"]))
    if cross.get("data_selfcheck") is not None:
        sc = cross["data_selfcheck"]
        rows.append(("数据自检(池前 20 · FMP vs Alpaca 收盘)", ("⚠偏差 " + " · ".join("%s %.2f/%.2f(%.1f%%)" % (m["symbol"], m["primary"], m["secondary"], m["dev_pct"]) for m in sc["mismatch"]))
                     if sc["mismatch"] else "%d 票一致,%d 票无第二源" % (sc["checked"], sc["unavailable"])))
    if cross.get("regime"):      # v3.29:宏观只进仓位档(Fable C#4),不进选股
        rg = cross["regime"]
        ev = rg.get("event") or {}
        rows.append(("事件层(数据日/巨头财报/美债/油)", ("⚠事件日 " if ev.get("event_day") else "") + ("; ".join(ev.get("why") or []) or "无高影响事件")
                     + ((" · 后续:" + " / ".join("%s %s" % (str(e.get("date"))[:10], e.get("event")) for e in (ev.get("upcoming_events") or [])[:4])) if ev.get("upcoming_events") else "")))
        rows.append(("仓位档(宏观 regime,只作仓位不选股)", "%s —— %s;Kelly:%s" % (rg.get("tier"), rg.get("why"), rg.get("kelly_note"))))
    if "trend_board" in cross:   # v3.28:自算趋势榜(不是 FMP 榜)
        tb = cross.get("trend_board") or []
        if tb:
            rows.append(("趋势榜(自算·全市场,因子分 F1资金/F2趋势/F3形态/F4事件/F5期权)", " · ".join(
                "%s %d[%s]%s" % (t["symbol"], t["trend_score"], t.get("trend_why", ""), ("⚠" + ",".join(t["flags"])) if t.get("flags") else "")
                for t in tb[:8])))
        else:
            rows.append(("趋势榜(自算)", "空——宇宙 %s 票(screener 失败=0)或全未过地板/最低分" % cross.get("trend_universe_n", "?")))
    # v3.26 引擎候选池:确定性排序独立于 DS 落屏——强票在不在池里、为何进不了,一行可查
    if "candidate_pool" in cross:
        pool = cross.get("candidate_pool") or []
        prej = cross.get("pool_rejected") or []
        if pool:
            rows.append(("引擎候选池(地板后·分[眼]·$%gM/20日)" % (fetchers.pool_adv_floor_usd() / 1e6), " · ".join(
                "%s %d分[%s]%s" % (p["symbol"], p["score"], "/".join(p.get("eyes") or []),
                                   ("⚠" + ",".join(p["flags"])) if p.get("flags") else "")
                for p in pool)))
        else:
            rows.append(("引擎候选池", "空——宇宙 %s 票全未过地板或无读数(见筛除行);S1 依规空槽"
                         % cross.get("pool_universe_n", "?")))
        if prej:
            rows.append(("候选池筛除(引擎地板)", "%d 票:" % len(prej) + " · ".join(
                "%s(%s)" % (r["symbol"], r["clause"]) for r in prej[:10]) + ("…" if len(prej) > 10 else "")))
    fr = cross.get("floor_rejected") or {}
    for k_, label_ in (("amc_tonight", "今晚财报·地板筛除"), ("bmo_tomorrow", "明日BMO·地板筛除"),
                       ("upcoming_earnings", "run-up·地板筛除")):
        if fr.get(k_):
            rows.append((label_, " · ".join("%s(%s)" % (r["symbol"], r["clause"]) for r in fr[k_][:8])
                         + ("…(共%d)" % len(fr[k_]) if len(fr[k_]) > 8 else "")))
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
            es = x.get("earn_score")
            return x.get("symbol", "?") + ("⚠" if hot else "") + ("(%d)" % es if es is not None else "")
        rows.append(("今晚财报(AMC,因子分 0–100,<40 禁 call,⚠=双杀风险位)",
                     " · ".join(_amcfmt(x) for x in cross["amc_tonight"][:6])))
    if cross.get("market_movers"):
        th = cross.get("theme_heat") or []
        if th:
            rows.append(("热簇·数据自聚(hot=钱在流入)", " · ".join(
                "%s(%d)%s avg%+.1f%%" % (t["theme"][:16], t["n"], "🔥" if t["hot"] else "",
                t["avg_chg"]) for t in th[:6])))
        ma = cross.get("most_active") or []
        if ma:
            rows.append(("最活跃榜(热资金)", " · ".join(
                "%s%s" % (x["symbol"], ("%+.1f%%" % x["chg_pct"]) if x.get("chg_pct") is not None else "")
                for x in ma[:10])))
        else:
            rows.append(("最活跃榜(热资金)", "⚠ 失败:%s——簇无资金确认,本班不发🔥"
                         % (cross.get("_ma_err") or "未知")))
        cm = cross.get("comove") or []
        if cm:
            def _cm_line(c):
                shown = c["members"][:8]
                tail = "" if len(c["members"]) <= 8 else "…(示%d/%d)" % (len(shown), c["n"])
                return "%s[团%d·ρ%s]%s中位%+.1f%%:%s%s" % ("🔥" if c["hot"] else "", c["n"],
                    c.get("cohesion", "?"), "$" if c["money"] else "", c["med_chg"],
                    " ".join(mm["symbol"] for mm in shown), tail)
            rows.append(("同频簇(两两ρ≥0.7·团)", " · ".join(_cm_line(c) for c in cm)))
        sb = cross.get("streak_board") or []
        if sb:
            rows.append(("连涨/连续上榜(3日≥2现)", " · ".join(sb[:14])))
        wlr = cross.get("watchlist") or []
        if wlr:
            rows.append(("自选名单(实测)", " · ".join(
                "%s%s" % (x["symbol"], ("%+.1f%%" % x["chg_pct"]) if x.get("chg_pct") is not None else "")
                for x in wlr[:14])))
        rows.append(("全市场异动(|chg|≥10%,非仅财报)", " · ".join(
            "%s%+.1f%%" % (x["symbol"], x["chg_pct"]) for x in cross["market_movers"][:8])))
    if cross.get("bmo_tomorrow"):
        def _bmofmt(x):
            hot = (x.get("chg5_pct") or 0) > 15 or (x.get("rsi14") or 0) > 75
            es = x.get("earn_score")
            return x.get("symbol", "?") + ("⚠" if hot else "") + ("(%d)" % es if es is not None else "")
        rows.append(("明日财报(BMO 伏击名单,因子分 0–100,⚠=双杀风险位)",
                     " · ".join(_bmofmt(x) for x in cross["bmo_tomorrow"][:6])))
    if cross.get("upcoming_earnings"):
        rows.append(("未来 1-8 日财报(run-up 窗,d=交易日)", " · ".join(
            "%s(%s d%s)" % (x["symbol"], (x.get("date") or "")[5:], x.get("days_out", "?")) for x in cross["upcoming_earnings"][:8])))
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
    if cross.get("amc_results_health"):   # v3.26.3:盘后 0 出数必须响亮报原因,不留空
        rows.append(("盘后读数健康态", cross["amc_results_health"]))
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
    if data is None and mode in ("morning", "midday", "earnings"):   # v3.26.3:失败必须上脸,禁留昨日页
        warn += ('<div class="banner" style="border-color:var(--red)"><b style="color:var(--red)">本班无有效作业</b>'
                 '<span>DS 无 JSON 产出——原因见下方正文;卡片缺席不是"今日无候选"</span></div>')
    body = warn + _engine_card(cross) + (_render_structured(date, data) if data else _md_fallback(raw_text))
    return ('<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"/>'
            '<meta name="viewport" content="width=device-width,initial-scale=1"/>'
            '<title>SCOUT · %s · %s</title><style>%s</style></head><body>'
            '<header><h1>SCOUT</h1><span class="sub">%s · %s · 数据as-of %s · 参谋作业,Lyra 拍板</span></header>'
            '%s<footer>build scout v3.31 · 反馈回路+事件层+六因子核+准入闸 · 三班制+BMO伏击+FMP路由 · FMP主源+Theta+Alpaca backup · emit/tape_check/rsi14_tape/源清单lint/EXPANDED-GLM · 影子lane · 账本卫生 · Grid降噪 · 四槽卡 · ET锚定 · '
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
        try:                       # v3.31 归因账本:池前 12 + 发出的实卡,带六因子子分与当时价
            attribution.log_rows(OUT, date, mode, attribution_rows(cross, data, mode))
        except Exception as exc:
            print("[scout] 归因账本写入失败:", exc)
    print("[scout] 落盘:", bp, "+", hp, "(+json)" if data is not None else "")


def main():
    ap = argparse.ArgumentParser(description="Scout Agent v3(DS 决策官)")
    ap.add_argument("--mode", choices=["evening", "morning", "midday", "earnings", "afterhours"], default="evening")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-fetch", action="store_true")
    ap.add_argument("--review", choices=["expanded", "off"], default="expanded",
                    help="已废弃可关:晚报 GLM 编译硬闸,off 仍会跑 expanded_evening_review")
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

    if (a.skip_fetch or a.mode == "afterhours") and os.path.exists(raw_path):
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
    if a.mode == "afterhours":
        run_afterhours_snapshot(payload, today); return

    yday = yesterday_raw(today)
    cross = cross_asset_summary(payload)
    if cross.get("liquidation_watch"):
        print("[scout] 引擎:全线下跌判据触发", cross)
    if a.mode in ("morning", "midday", "earnings"):
        shift = a.mode
        if shift == "earnings":
            # 财报班(开卷):四件套全上——movers 硬闸 / 今晚 AMC / 明日 BMO / 1-8 日 run-up
            cross["earnings_movers"] = earnings_movers(payload, today)
            cross["amc_tonight"] = amc_tonight(payload, today)
            cross["bmo_tomorrow"] = bmo_tomorrow(payload, today)
            cross["upcoming_earnings"] = upcoming_earnings(payload, today)
        else:
            # v3.25.6:morning/midday 都算 amc_tonight——S2 初筛卡名单源(观察不建仓,
            # 非财报持仓腿,与 2026-08-19"6:45 不含财报腿"拍板不冲突)
            cross["amc_tonight"] = amc_tonight(payload, today)
        cross["market_movers"] = market_movers(payload)
        cross["most_active"] = most_active(payload)
        cross["_ma_err"] = most_active_health(payload)
        cross["theme_heat"] = theme_heat(payload)
        cross["comove"] = comove_clusters(payload)
        cross["streak_board"] = update_streaks(today, cross["market_movers"], cross["most_active"])
        _wl = load_watchlist()
        if _wl:
            cross["watchlist"] = [dict({"symbol": s}, **(fetchers._stooq_daily(s.lower() + ".us", s, "watchlist") or {})) for s in _wl]
        # v3.26:确定性候选池(六眼→实测→地板→计分)+ 财报三名单过地板,先于 DS 看见
        cross["regime"] = regime_and_kelly(payload)
        cross["trend_board"], cross["trend_universe_n"], cross["trend_rejected_n"] = trend_board(today)
        print("[scout] 趋势榜 %d(宇宙 %d):%s" % (len(cross["trend_board"]), cross["trend_universe_n"],
              " ".join("%s(%d)" % (t["symbol"], t["trend_score"]) for t in cross["trend_board"][:6]) or "空"))
        cross["candidate_pool"], cross["pool_rejected"], cross["pool_universe_n"] = candidate_pool(
            cross, view=("t0" if shift in ("morning", "midday") else "swing"))   # v3.29.3:晨午班 0DTE 视角
        floor_earnings_lists(cross)
        print("[scout] 候选池 %d/%d 过地板:%s" % (len(cross["candidate_pool"]), cross["pool_universe_n"],
              " ".join("%s(%d)" % (p["symbol"], p["score"]) for p in cross["candidate_pool"][:6]) or "空"))
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
        prompt = build_trading_prompt(payload, ws, yday, cross, prev, shift=shift, todays=todays,
                                      fault_lines=(load_fault_lines_snapshot(today)[0] if shift == "morning" else ""))
        ds_err = ""
        try:
            body = ds_call(prompt)
        except SystemExit:
            raise
        except Exception as e:   # v3.26.3:超时/网络类失败不崩班——失败标记+html 必须覆盖昨日页
            body, ds_err = "", "DS 调用失败(%s)" % str(e)[:120]
            print("[scout]", ds_err)
        data = _extract_json(body) if (body or "").strip() else None
        if data is None:
            hint = (ds_err or "DS 空正文(finish=length/未关 think 类,8-17 案)") if not (body or "").strip() \
                else "疑输出截断,查 DS_MAX_TOKENS" if body.lstrip().startswith("{") \
                else "DS 未按 schema"
            body = body or ("[scout] 本班 DS 无有效产出:" + hint)
            print("[scout] 晨会单 JSON 解析失败(%s)——降级文本渲染,json 落失败标记(land 拒吃口)" % hint)
            os.makedirs(os.path.join(OUT, "briefs"), exist_ok=True)
            with open(os.path.join(OUT, "briefs", "%s-%s.json" % (today, shift)), "w", encoding="utf-8") as f:
                json.dump({"_engine": cross, "ds": {"_parse_failed": True, "hint": hint}},
                          f, ensure_ascii=False, indent=1)
        else:
            data = apply_liquidity_gate(data)
            data = apply_tape_check(data)
            data = apply_quality_floor(data, shift, cross)   # v3.26:会改卡(地板作废),先于下限盖章
            data = apply_candidate_floor(data, shift)
        render_console(title, body, today, shift, data, cross)
        if shift == "morning":
            glm_morning_land_or_die(today)   # GLM 编译后才算落盘(land 内 emit)
        else:
            emit_aether_scout(today, shift, title, data, cross, body)
        _scout_bark(shift, today, data if isinstance(data, dict) else {})
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
        cross["market_movers"] = market_movers(payload)
        cross["most_active"] = most_active(payload)
        cross["_ma_err"] = most_active_health(payload)
        cross["theme_heat"] = theme_heat(payload)
        cross["comove"] = comove_clusters(payload)
        cross["streak_board"] = update_streaks(today, cross["market_movers"], cross["most_active"])
        _wl = load_watchlist()
        if _wl:
            cross["watchlist"] = [dict({"symbol": s}, **(fetchers._stooq_daily(s.lower() + ".us", s, "watchlist") or {})) for s in _wl]
        cross["amc_tonight"] = amc_tonight(payload, today)
        # v3.26.3(戌 8-24 抓:晚报没吃候选池和财报地板——闸只挂白班,晚报仍把 PICS 当过夜腿、
        # 仍叫人看 IBIT/BITO):晚班同一套纪律——候选池(明日弹药视野)+ 三名单过地板
        cross["bmo_tomorrow"] = bmo_tomorrow(payload, today)
        cross["upcoming_earnings"] = upcoming_earnings(payload, today)
        cross["regime"] = regime_and_kelly(payload)
        cross["trend_board"], cross["trend_universe_n"], cross["trend_rejected_n"] = trend_board(today)   # 晚班算,次晨共用
        cross["candidate_pool"], cross["pool_rejected"], cross["pool_universe_n"] = candidate_pool(cross)
        floor_earnings_lists(cross)
        # v3.25.2(COTY 案):盘后查询名单 = amc_tonight(地板后)∪ 当日各班非空候选腿(预排卡除外)
        ah_syms = afterhours_symbols(cross, today)
        if ah_syms:
            snap = load_afterhours_snapshot(today)
            if snap:
                ah, cross["amc_results_health"] = snap, ("盘后快照 %s:%d/%d 出数" % (
                    snap.get("asof", "?")[11:16], sum(1 for i in snap.get("items") or [] if i.get("ah_chg_pct") is not None), len(ah_syms)))
            else:
                n0 = len(fetchers.SKIPS)
                ah = fetchers.fetch_afterhours(sorted(ah_syms)[:24])
                cross["amc_results_health"] = afterhours_health(ah, ah_syms, fetchers.SKIPS[n0:])
            cross["amc_results"] = sorted(
                [i for i in (ah.get("items") or []) if i.get("ah_chg_pct") is not None],
                key=lambda x: -abs(x["ah_chg_pct"]))
            print("[scout] 盘后读数:", cross["amc_results_health"])
        evening_feedback(cross, today)     # v3.31:结算归因账本、因子 IC 表、数据自检
        rev = build_review(today)
        build_review(today, "-glm")   # 影子 lane 分账复盘(无影子文件则静默跳过)
        if rev:
            rev["rolling"] = rolling_summary(today)
            cross["today_review"] = {"date": today, "hit": rev["hit"], "rolling": rev["rolling"]}
        inv = source_inventory(payload)
        prompt = build_evening_prompt(payload, yday, cross, rev, inv, today=today)
        body = evening_ds_with_lint(prompt, payload)
        render_console("Scout 晚报复盘 · " + today, body, today, "evening", None, cross)
        # 晚报 GLM 编译硬闸:--review off 不再合法,空回/失败禁止 emit
        glm_txt = expanded_evening_review(today, body)
        if not glm_txt:
            raise SystemExit("晚报 GLM 编译未完成——禁止落盘")
        emit_aether_scout(today, "evening", "Scout 晚报复盘 · " + today, None, cross, body)
        persist_skips(raw_path, payload)


if __name__ == "__main__":
    main()
