#!/usr/bin/env python3
"""Scout Agent · 本机装包后门禁(失败非零退出)。

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
        _fail("晨会 RSI 铁律或 yday[:4000] 未按 v3.16.2")

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

    # v3.16 晚班三处
    if "et_now_hm()" in sa and "收盘后;今日 AMC 财报已披露" in sa:
        _ok("晚班 prompt 含 ET et_now_hm 钟点")
    else:
        _fail("晚班缺 et_now_hm(收盘后;今日 AMC 财报已披露)")
    if '财报"已出结果"者名单' in sa or "已出结果" in sa and "若超预期" in sa and "禁止出现" in sa:
        _ok("晚班 §5 AMC 已出叙事(禁若超预期)")
    else:
        _fail("晚班 §5 未按 v3.16 已出叙事改写")
    if "今日已出结果者不属 run-up" in sa and '"watch"' in sa:
        _ok("晚班 §6 run-up 仅未来日 + build_review.watch")
    else:
        _fail("晚班缺 v3.16 run-up 边界或 review.watch")


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
