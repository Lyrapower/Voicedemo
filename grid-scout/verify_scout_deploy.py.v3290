#!/usr/bin/env python3
"""Scout Agent · 本机装包后门禁(失败非零退出)。v3.24 增补 FMP/Theta 三项。

装任何 scout_agent_install*.sh 进本目录后必须跑通本脚本,才算部署完成。
禁止口头「已装好」——只认本门禁绿。

门禁项:
  1) 代码: Ollama 路径 think=false
  2) 代码: emit_aether_scout 存在且 morning/evening 主路径调用
  3) 代码: Alpaca/SSL/日历 wrap≥800 / amc_tonight 非 [:15]
  4) 代码: cross_asset_summary 产出 rsi14_tape
  5) 代码: v3.16 晚班(et_now_hm 钟点 / 已出叙事 / run-up 仅未来日 / review.watch)
  6) 实况: 今日 AMC 日历非空;若日历含 TEAM 则 amc_tonight 必须含 TEAM
  7) 实况: rsi14_tape 至少 SP500+NASDAQ 有非空 rsi14
  8) 实况: GATEWAY /store 可达(emit 前置)

用法:
  cd /Users/ciciwang/Projects/demo/grid-scout
  python3 verify_scout_deploy.py
  python3 verify_scout_deploy.py --skip-live   # 仅静态代码闸
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

FAILS: list[str] = []
OKS: list[str] = []


def _fail(msg: str) -> None:
    FAILS.append(msg)
    print("  FAIL ", msg)


def _ok(msg: str) -> None:
    OKS.append(msg)
    print("  OK   ", msg)


def gate_static_code() -> None:
    print("[1] 静态代码闸")
    sa_path = os.path.join(HERE, "scout_agent.py")
    fe_path = os.path.join(HERE, "fetchers.py")
    sa = open(sa_path, encoding="utf-8").read()
    fe = open(fe_path, encoding="utf-8").read()

    # think=false for Ollama
    if re.search(r'body\s*\[\s*["\']think["\']\s*\]\s*=\s*False', sa) or re.search(
        r'["\']think["\']\s*:\s*False', sa
    ):
        _ok("ds_call 含 think=False")
    else:
        _fail("ds_call 未强制 think=False(Ollama 长单会空正文)")

    # emit wired
    if "def emit_aether_scout" not in sa:
        _fail("缺少 emit_aether_scout")
    elif sa.count("emit_aether_scout(") < 3:  # def + morning + evening
        _fail("emit_aether_scout 未在 morning/evening 主路径各调一次")
    else:
        _ok("emit_aether_scout 已接线 morning+evening")

    # rsi14_tape
    if 'out["rsi14_tape"]' in sa or "rsi14_tape" in sa:
        _ok("cross 含 rsi14_tape")
    else:
        _fail("cross_asset_summary 未产出 rsi14_tape")

    # amc cap not stuck at 15 (v3.16.2 返回 dict 列表,截断在 out=out[:N])
    m = re.search(r"out\s*=\s*out\[:(\d+)\]", sa)
    if not m:
        m = re.search(r"def amc_tonight[\s\S]+?return out\[:(\d+)\]", sa)
    if not m:
        _fail("amc_tonight 未找到名单截断 out[:N]")
    else:
        n = int(m.group(1))
        if n < 30:
            _fail("amc_tonight cap=%d(<30)——TEAM 等中盘会被裁" % n)
        else:
            _ok("amc_tonight cap=%d" % n)
    if 'tape_check' in sa and 'RSI/tape 实测(引擎)' in sa:
        _ok("v3.16.2 tape_check + 候选卡 RSI 行")
    else:
        _fail("缺 tape_check 盖章或 RSI/tape 实测行")
    if "禁止自估 RSI" in sa and "yday, ensure_ascii=False)[:4000]" in sa:
        _ok("晨会 RSI 禁自估 + 晚班 yday 截断4000")
    else:
        _fail("晨会 RSI 硬规则或 yday[:4000] 未按 v3.16.2")

    # fetchers local path
    if "def _ssl_context" not in fe:
        _fail("fetchers 缺 _ssl_context(certifi)")
    else:
        _ok("fetchers._ssl_context")
    if "def alpaca_snapshots" not in fe or "def alpaca_daily_closes" not in fe:
        _fail("fetchers 缺 Alpaca snapshots/bars(本机 stooq 被墙时 rsi14 必空)")
    else:
        _ok("fetchers Alpaca snapshots + daily_closes(RSI)")
    if "class quote_layer" in fe and "def quote_layer_snapshot" in fe and "ALPACA_KEY_ID" in fe:
        _ok("v3.16§⑦ quote_layer + ALPACA_KEY_ID 别名")
    else:
        _fail("缺 quote_layer 缝或 ALPACA_KEY_ID 别名(v3.16§⑦)")
    if "feed_ah_label" in fe and "data_plane_banner" in fe:
        _ok("feed 档标签 + 数据层横幅")
    else:
        _fail("缺 feed_ah_label / data_plane_banner")
    if "800 if source" not in fe and "earnings_calendar" not in fe:
        _fail("earnings_calendar 源级 wrap 未升到可容纳热日+今日")
    elif re.search(r"800 if source\s*==\s*[\"']earnings_calendar[\"']", fe):
        _ok("earnings_calendar wrap≥800")
    else:
        # soft: look for cap =
        if "earnings_calendar" in fe and "800" in fe:
            _ok("earnings_calendar wrap 含 800")
        else:
            _fail("earnings_calendar wrap 仍可能是 40/240——会吞今日 AMC")

    # v3.24 数据链三项(FMP 主源→Theta 第二源→Alpaca backup,Lyra 拍板 2026-08-17)
    if "def _fmp_history" in fe and "def _history" in fe and "FMP_API_KEY" in fe:
        _ok("v3.24 FMP 主源缝(_fmp_history/_history)")
    else:
        _fail("缺 FMP 主源缝——数据链未按 2026-08-17 拍板落地")
    if "_theta_history" in fe and "THETA_BASE" in fe:
        _ok("v3.24 Theta 第二源(探活跳过式,不强迫起容器)")
    else:
        _fail("缺 Theta 第二源链位")
    if "PRICES_DIR" in fe and "fmp_calls_today" in fe:
        _ok("v3.24 K线缓存 + FMP 调用记账(免费档 250/日)")
    else:
        _fail("缺 prices/ 缓存或 FMP 记账——调试重跑日会烧穿配额")

    # v3.16 晚班三处
    if "et_now_hm()" in sa and "收盘后;今日 AMC 财报已披露" in sa:
        _ok("晚班 prompt 含 ET et_now_hm 钟点")
    else:
        _fail("晚班缺 et_now_hm(收盘后;今日 AMC 财报已披露)")

    if (
        "def source_inventory" in sa
        and ("采集源清单(权威·" in sa or "采集源清单(权威)" in sa)
        and "ok=true" in sa
    ):
        _ok("晚班源清单纪律(禁伪称 SSL/缺失)")
    else:
        _fail("晚班缺 source_inventory / 采集源清单纪律")
    if (
        "def lint_evening_source_claims" in sa
        and "def evening_ds_with_lint" in sa
        and "事实行(最高权威" in sa
    ):
        _ok("晚班源清单硬闸 v3.16.4(事实行+lint 重写)")
    else:
        _fail("晚班缺 v3.16.4 lint_evening_source_claims / evening_ds_with_lint")
    if (
        "def expanded_evening_review" in sa
        and "/gateway/task/expanded" in sa
        and "scout_expanded_memory_node" in sa
        and "scout-review-" in sa
        and "cloud_backend" in sa
        and "glm52_cloud" in sa
        and 'a.review == "expanded"' in sa
    ):
        _ok("晚报 EXPANDED-GLM review v3.16.5(8515→8501 · scout-review-日)")
    else:
        _fail("晚报缺 expanded_evening_review / scout-review-日 / glm52_cloud 接线")
    if '财报"已出结果"者名单' in sa or "已出结果" in sa and "若超预期" in sa and "禁止出现" in sa:
        _ok("晚班 §5 AMC 已出叙事(禁若超预期)")
    else:
        _fail("晚班 §5 未按 v3.16 已出叙事改写")
    if "今日已出结果者不属 run-up" in sa and '"watch"' in sa:
        _ok("晚班 §6 run-up 仅未来日 + build_review.watch")
    else:
        _fail("晚班缺 v3.16 run-up 边界或 review.watch")

    # ---- v3.25 三班制 + BMO 伏击 + FMP 路由 ----
    if '"midday"' in sa and '"earnings"' in sa and "choices=" in sa:
        _ok("v3.25 --mode 含 midday/earnings")
    else:
        _fail("v3.25 --mode choices 缺 midday/earnings")
    if (
        "def bmo_tomorrow" in sa
        and "def upcoming_earnings" in sa
        and "def build_handover" in sa
        and "def persist_skips" in sa
    ):
        _ok("v3.25 新引擎器官(bmo_tomorrow/upcoming_earnings/build_handover/persist_skips)")
    else:
        _fail("v3.25 缺新引擎器官")
    if "pre-market" in sa and "time-after-hours" in sa.lower() or "pre-market" in sa:
        _ok("v3.25 BMO 名单按 when 含 pre-market 匹配")
    else:
        _fail("v3.25 BMO 名单未按实值 time-pre-market 匹配")
    if (
        "def _fmp_call_routed" in fe
        and "FMP_RATE_PER_MIN" in fe
        and ".fmp_route" in fe
        and "_FMP_STABLE_BASE" in fe
    ):
        _ok("v3.25 FMP 端点路由器(自探定版+节流)")
    else:
        _fail("v3.25 fetchers 缺 FMP 端点路由器")
    if "_cache_save" in fe and "__proxy_" in fe:
        _ok("v3.25 缓存带血统(src 记账+代理独立键)")
    else:
        _fail("v3.25 缺缓存血统")
    if "def fetch_market_movers" in fe and "def market_movers" in sa and "biggest-gainers" in fe:
        _ok("v3.25.2 全市场异动扫描(源+引擎)")
    else:
        _fail("v3.25.2 缺全市场异动扫描")
    if 'WB + "/gateway/task/expanded"' in sa and '"task": (final_md or "")[:_cap]' in sa and "EXPANDED_TASK_CHARS" in sa:
        _ok("v3.25.2 expanded review b286083 形制(WB+task+final;v3.26.3 task 字数走 EXPANDED_TASK_CHARS 默认 8000)")
    else:
        _fail("v3.25.2 expanded review 形制回滚(缺 WB/task)")
    if "def fetch_most_active" in fe and "def theme_heat" in sa and "industry_lookup" in fe:
        _ok("v3.25.8 全视野器官(最活跃榜+热簇数据自聚)")
    else:
        _fail("v3.25.8 缺全视野器官")
    if "THEMES = {" not in sa:
        _ok("v3.25.8 无手写主题表(热点数据自聚)")
    else:
        _fail("手写主题表残留(2026-08-21 Lyra 禁令:禁写死范围)")
    if "def update_streaks" in sa and "streak_board" in sa:
        _ok("v3.25.8 连涨账本")
    else:
        _fail("v3.25.8 缺连涨账本")
    if "def apply_candidate_floor" in sa and 'apply_candidate_floor(data, shift)' in sa:
        _ok("v3.25.7/8 候选下限代码闸挂载")
    else:
        _fail("候选下限纯 prompt 零核查(v3.25.6 复审①回滚)")
    if '"morning", "midday", "earnings"' in sa.split("def apply_candidate_floor")[1][:400] and "禁止只在板块 ETF" in sa:
        _ok("v3.25.8 earnings 入下限+S1 全视野改写")
    else:
        _fail("v3.25.8 范围/S1 改写回滚")
    if "def _scout_bark" in sa and "group=scout-brief" in sa:
        _ok("v3.25.8 班次 bark 回流(戌 L1524)")
    else:
        _fail("v3.25.8 班次 bark 未回流(下包将踩掉现场热修)")
    if "本班默认不建新仓" not in sa:
        _ok("v3.25.7 midday 矛盾清除")
    else:
        _fail("midday 默认收敛矛盾残留(v3.25.6 复审①)")
    # 全局名可解析(2026-08-23 _NOISE_RX 案:定义丢五版,冒烟没走 evening 链,NameError
    # 现场首炸。此检查静态杀全族:两模块每个函数字节码引用的全局名必须可解析)
    import importlib, builtins, types, dis
    _bad = []
    for _modname in ("scout_agent", "fetchers"):
        try:
            _mod = importlib.import_module(_modname)
        except Exception as _e:
            _bad.append("%s import 失败:%s" % (_modname, str(_e)[:80]))
            continue
        for _fname in dir(_mod):
            _fn = getattr(_mod, _fname)
            if isinstance(_fn, types.FunctionType) and _fn.__module__ == _modname:
                for _ins in dis.get_instructions(_fn):
                    if _ins.opname == "LOAD_GLOBAL":
                        _n = _ins.argval
                        if not hasattr(_mod, _n) and not hasattr(builtins, _n):
                            _bad.append("%s.%s 引用未定义全局名 %s" % (_modname, _fname, _n))
    if _bad:
        _fail("全局名不可解析:" + " | ".join(sorted(set(_bad))[:6]))
    else:
        _ok("全局名可解析(两模块全函数字节码扫描)")
    if "money_confirmed" in sa and "actives_set" in sa and "本班不发🔥" in sa:
        _ok("v3.25.10 热簇资金确认+失败响亮自证")
    else:
        _fail("v3.25.10 资金确认/自证缺失(壳公司冒充热簇案回滚)")
    if "def _next_trading_day" in sa and "晚报无立法权" in sa:
        _ok("v3.25.10 日历纪律+晚报效力边界")
    else:
        _fail("v3.25.10 日历/立法边界缺失")
    if ("def comove_clusters" in sa and 'cross["comove"]' in sa and "def _max_cliques" in sa
            and "med_chg" in sa and ">= 2" in sa.split("def comove_clusters")[1][:6000]):
        _ok("v3.25.15 同频簇=极大团+中位hot+双名资金确认(三路云审刀)")
    else:
        _fail("同频簇团定义缺失(朋友圈案回滚:连通分量/均值hot/单名连坐)")
    if "def sector_flow" not in sa:
        _ok("sector 永真桶已拆净")
    else:
        _fail("sector_flow 永真桶残留(2026-08-24 Lyra 否决)")
    if ("def load_fault_lines_snapshot" in sa and "fault_lines=(load_fault_lines_snapshot" in sa
            and "退避重试" in sa and "去 think 重试" in sa):
        _ok("v3.25.12 戌四处回流(断层读取器/晨会接线/ds 韧性)")
    else:
        _fail("戌四处回流缺失(下包将踩掉现场施工)")
    # ---- v3.26(2026-08-24 财报班垃圾案:PICS $5 无实测出卡 / PATH 十分钟 0DTE / BMNR 落榜)----
    if ("def candidate_pool" in sa and 'cross["candidate_pool"]' in sa and "def apply_quality_floor" in sa
            and "apply_quality_floor(data, shift, cross)" in sa and "def floor_earnings_lists" in sa
            and "floor_earnings_lists(cross)" in sa and "adv20_usd" in fe and "def pool_price_floor" in fe):
        _ok("v3.26 引擎候选池+质量地板代码闸挂载(实测 price/adv20_usd)")
    else:
        _fail("v3.26 候选池/地板闸缺失(六眼只当参考、DS 自由挑、无实测照出卡案回滚)")
    if "price<$5" not in sa and "floor_rejected" in sa and "_floor_kills" in sa:
        _ok("v3.26 财报名单地板后供 DS+作废可审($5 prompt 文字规则已废)")
    else:
        _fail("v3.26 名单地板/作废留痕缺失或 $5 纯 prompt 规则残留")
    if sa.count("明晨预排") >= 3 and "禁 0DTE、禁今日尾盘入场" in sa:
        _ok("v3.26 财报班 S1/S3=明晨预排(prompt+代码前缀+复盘不计命中)")
    else:
        _fail("v3.26 财报班预排缺失(收盘前 15 分钟 0DTE 刮单案回滚)")
    if "kept >= 50" in fe and '120 if source == "market_movers"' in fe:
        _ok("v3.26 movers 抓取 50/侧(真流动 +15% 票被壳票挤出前 20 的盲区)")
    else:
        _fail("v3.26 movers 抓取 cap 回滚到 20")
    if "ETF 不入池" in sa and '"is_etf"' in fe and "ETF 不入候选" in sa:
        _ok("v3.26.1 ETF 硬排(profile isEtf;池+S1/S3 点名两处)")
    else:
        _fail("v3.26.1 ETF 硬排缺失(最活跃榜 ETF 占池、高 IV 单票被挤案回滚)")
    if "def _sort_earn" in sa and '"earn_score"' in sa and "形态错配" in sa and "TAPE_VETO_CHG" in sa and "按市值)未点名" not in sa:
        _ok("v3.27 财报名单按尾盘形态分排+方向/形态错配作废(8-25 INTU 案)")
    else:
        _fail("v3.27 尾盘形态分/错配作废缺失(弱势收低票持过财报 call 案回滚)")
    if "def fmp_board_syms" in sa and "不在当日榜" in sa and os.path.exists(os.path.join(HERE, "acceptance_fmp_board.py")):
        _ok("v3.27.1 财报 call 腿必须在当日榜(资金确认)+ 名单 fmp_board 标记 + 现场验收脚本在场")
    else:
        _fail("v3.27.1 榜硬门/验收脚本缺失(Lyra:不在 top mover 榜的不收)")
    if ("def trend_board(" in sa and '"趋势🔥"' in sa and "def fetch_screener_universe" in fe
            and "def history_snapshot" in fe and '"up5"' in fe and 'cross.get("trend_board")' in sa):
        _ok("v3.28 自算趋势榜(第七只眼,BMNR 案:FMP 两榜天生看不见连涨大票)")
    else:
        _fail("v3.28 趋势榜缺失(连涨一周的趋势票再次隐形)")
    if "if vol > 0 and px * vol < 5e7" in fe and "volume0_passed" in fe:
        _ok("v3.28.1 screener volume=0 放行(BMNR volume=0 被粗筛误杀案)")
    else:
        _fail("v3.28.1 screener 粗筛仍会误杀 volume=0 的票")
    if "def _last_closed_session(today, now_et=None)" in sa and "def now_et" in fe and "need_date=key" in sa and "coverage >= 0.5" in sa and '"last_bar_date"' in fe:
        _ok("v3.28.2 趋势榜时钟(晚班键=当日、次晨同键零重算)+ 当日 EOD 覆盖自证(不足不落盘)")
    else:
        _fail("v3.28.2 趋势榜时钟/覆盖自证缺失(晚班算昨榜、次晨重算 1200 票案)")
    fp = os.path.join(HERE, "factors.py")
    fx = open(fp, encoding="utf-8").read() if os.path.isfile(fp) else ""
    old_rules = [k for k in ("最活跃+3", "趋势榜+3", "同频团+2", "热簇+1", "近52周高+1", "收高位+1", "FMP榜+2") if k in sa]
    if (fx and "FACTOR_BUDGET" in fx and "def score(" in fx and "import factors" in sa and "factors.score(" in sa
            and not old_rules and "/v3/option/snapshot/greeks/all" in fe and "def regime_and_kelly(" in sa):
        try:
            sys.path.insert(0, HERE); import factors as _f
            n_f = len(_f.FACTORS); ok_budget = n_f <= _f.FACTOR_BUDGET
        except Exception as exc:
            n_f, ok_budget = -1, False
        if ok_budget:
            _ok("v3.29 六因子核(factors.py,%d 因子 ≤ 预算 %d)替代手写规则;F5 Theta greeks 端点按官方文档;仓位档/Kelly 只显示" % (n_f, _f.FACTOR_BUDGET))
        else:
            _fail("v3.29 因子数超预算(过拟合危险区)")
    else:
        _fail("v3.29 因子核缺失或手写规则回流:%s" % (old_rules or "factors.py/接线缺"))
    if ('"days_out"' in sa and 'if dt == nd and "pre-market" in when' in sa and "far >= 6" in sa):
        _ok("v3.26.2 run-up 单收次日 AMC(d1)+近远窗各自座位(NVDA 周二盲区案)")
    else:
        _fail("v3.26.2 run-up 单次日 AMC 盲区回滚(周二班看不见周三盘后 NVDA)")
    # ---- v3.26.3(戌 8-24 晚报审:晚报纪律/逗号票/晨会超时/GLM 闸/盘后空)----
    _ev = sa.split("        # 雷达第5项供数")[1][:4000] if "        # 雷达第5项供数" in sa else ""
    if "candidate_pool(cross)" in _ev and "floor_earnings_lists(cross)" in _ev and "amc_results_health" in sa:
        _ok("v3.26.3 晚班吃候选池+三名单地板+盘后健康态")
    else:
        _fail("v3.26.3 晚班未挂候选池/地板(晚报仍拿 PICS 当过夜腿案回滚)")
    if "逗号票" in sa and "一卡一票" in sa:
        _ok("v3.26.3 逗号票作废(非单一代码绕闸案)")
    else:
        _fail("v3.26.3 逗号票绕闸未堵")
    if "DS_TIMEOUT" in sa and "DS 调用失败(" in sa and "本班无有效作业" in sa and '"afterhours"' in sa and "def run_afterhours_snapshot" in sa:
        _ok("v3.26.3 DS 超时可调+失败落页+afterhours 快照班")
    else:
        _fail("v3.26.3 晨会超时崩班/盘后快照缺失")


def gate_live() -> None:
    print("[2] 实况闸(采日历+指数 RSI + gateway)")
    # load .env lightly
    envp = os.path.join(HERE, ".env")
    if os.path.isfile(envp):
        for ln in open(envp, encoding="utf-8"):
            s = ln.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, _, v = s.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v

    import fetchers
    import scout_agent as sa

    sa.OUT = HERE
    fetchers.SKIPS.clear()

    cal = fetchers.fetch_earnings_calendar()
    if not cal.get("ok"):
        _fail("earnings_calendar ok=False: %s" % (cal.get("error") or "?"))
        today_amc = []
        team_in_cal = False
    else:
        today = fetchers.trading_date().isoformat()
        items = cal.get("items") or []
        today_amc = [
            (it.get("symbol") or "").upper()
            for it in items
            if str(it.get("date") or "")[:10] == today
            and "after" in (it.get("when") or "").lower()
            and re.fullmatch(r"[A-Z]{1,5}", (it.get("symbol") or "").upper())
        ]
        team_in_cal = "TEAM" in today_amc
        if not today_amc:
            _fail("今日 AMC 日历为空(检查 wrap/热日/日期锚)")
        else:
            _ok("今日 AMC 日历 n=%d" % len(today_amc))

        payload = {"results": [cal]}
        amc = sa.amc_tonight(payload, today)
        amc_syms = [
            (x.get("symbol") if isinstance(x, dict) else x) or ""
            for x in (amc or [])
        ]
        amc_syms = [s.upper() for s in amc_syms]
        # v3.16.2: 带读数(至少一票有 chg_pct)
        if amc and isinstance(amc[0], dict) and any(
            isinstance(x, dict) and x.get("chg_pct") is not None for x in amc
        ):
            _ok("amc_tonight 带 Alpaca 读数(chg_pct)")
        elif amc:
            _fail("amc_tonight 未带 chg_pct 读数(v3.16.2)")
        if team_in_cal and "TEAM" not in amc_syms:
            _fail("日历含今日 AMC TEAM 但 amc_tonight 无 TEAM(cap/过滤)")
        elif team_in_cal:
            _ok("TEAM ∈ amc_tonight(日历有今日 AMC)")
        else:
            _ok("今日日历无 TEAM——跳过 TEAM 专检(名单仍须非空)")
            if not amc:
                _fail("amc_tonight 为空")

    # RSI via indices+hedge
    idx = fetchers.fetch_indices()
    hed = fetchers.fetch_hedge_assets()
    payload2 = {"results": [r for r in (idx, hed) if r]}
    cross = sa.cross_asset_summary(payload2)
    tape = cross.get("rsi14_tape") or []
    by = {x.get("name"): x.get("rsi14") for x in tape if isinstance(x, dict)}
    need = ("SP500", "NASDAQ")
    missing = [n for n in need if by.get(n) is None]
    if missing:
        _fail("rsi14_tape 缺实测: %s (现 %s)" % (missing, by))
    else:
        _ok("rsi14_tape SP500=%s NASDAQ=%s" % (by.get("SP500"), by.get("NASDAQ")))

    # FMP key(主源无弹 = 全链退 backup,响亮)
    if os.getenv("FMP_API_KEY", "").strip():
        _ok("FMP_API_KEY 在位(主源有弹)")
    else:
        _fail("FMP_API_KEY 未配置——主源无弹,全班退 Theta/Alpaca backup")

    # gateway reachable for emit
    gw = os.getenv("GATEWAY_URL", "http://127.0.0.1:8501").rstrip("/")
    try:
        req = urllib.request.Request(gw + "/health", method="GET")
        with urllib.request.urlopen(req, timeout=8) as resp:
            if 200 <= resp.status < 300:
                _ok("gateway %s/health 可达(emit 前置)" % gw)
            else:
                _fail("gateway health status=%s" % resp.status)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        _fail("gateway 不可达,emit 必失败: %s" % e)


def main() -> int:
    ap = argparse.ArgumentParser(description="Scout 本机装包后门禁")
    ap.add_argument("--skip-live", action="store_true", help="只跑静态代码闸")
    a = ap.parse_args()
    print("=== verify_scout_deploy · %s ===" % HERE)
    gate_static_code()
    if not a.skip_live:
        gate_live()
    else:
        print("[2] 实况闸 SKIP(--skip-live)")
    print("---")
    print("OK %d · FAIL %d" % (len(OKS), len(FAILS)))
    if FAILS:
        print("门禁未过——禁止宣称部署完成。失败项:")
        for f in FAILS:
            print("  -", f)
        return 1
    print("门禁通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
