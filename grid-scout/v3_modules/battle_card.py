"""组装晨报作战单 / 晚报复盘 Markdown。数字模块不过 LLM。"""
from __future__ import annotations
import json
from . import call_cards, oi_probe, odds_news, sectors, workstation


def _fmt_num(v, nd=1):
    if v is None:
        return "—"
    try:
        if abs(float(v) - int(float(v))) < 1e-9:
            return str(int(float(v)))
        return ("%." + str(nd) + "f") % float(v)
    except Exception:
        return str(v)


def _arrow(rel):
    if rel is None:
        return "·"
    if rel >= 1.0:
        return "↑↑"
    if rel >= 0.3:
        return "↑"
    if rel <= -1.0:
        return "↓↓"
    if rel <= -0.3:
        return "↓"
    return "→"


def render_morning_md(date: str, pack: dict) -> str:
    oi = pack["oi"]
    sec = pack["sectors"]
    calls = pack["calls"]
    ws = pack["ws"]
    odds = pack["odds"]
    news = pack["news"]
    lines = []
    lines.append("# 作战单 · %s (Scout v3)" % date)
    lines.append("")
    lines.append("定位:给 Lyra 的作战数字。①②③④ 全确定性;⑤ DS 只缩编要闻。")
    lines.append("「买」字不写——数字摆齐,决定归你。")
    lines.append("")

    # ①
    lines.append("## ① OI 异动探针  [源:Polygon options starter]")
    if not oi.get("ok"):
        lines.append("**BLOCKED** · %s" % (oi.get("error") or "unavailable"))
        lines.append("规则:`%s`" % oi.get("rule", ""))
    else:
        lines.append("规则:`%s` · 排序口径:`%s`" % (oi.get("rule"), oi.get("metric")))
        for r in oi.get("rows") or []:
            delta = r.get("oi_delta")
            d_s = ("+%s" % delta) if delta is not None and delta >= 0 else str(delta)
            star = " ★" if r.get("star") else ""
            if delta is not None:
                lines.append("- %s %s%s" % (r.get("label"), d_s, star))
            else:
                lines.append(
                    "- %s vol=%s OI=%s Vol/OI=%s%s"
                    % (r.get("label"), r.get("volume"), r.get("oi"), r.get("vol_oi"), star)
                )
        if oi.get("stars"):
            lines.append("Vol/OI>3 异常:")
            for r in oi["stars"][:5]:
                lines.append("- %s (Vol/OI %s)" % (r.get("label"), r.get("vol_oi")))
    lines.append("")

    # ②
    lines.append("## ② 板块轮动  [源:FMP]")
    if not sec.get("ok"):
        lines.append("**BLOCKED** · %s" % (sec.get("error") or "unavailable"))
    else:
        if sec.get("note"):
            lines.append("_%s_" % sec["note"])
        for r in sec.get("rows") or []:
            lines.append(
                "- %s %+s/%s/%s %s"
                % (
                    r["sym"],
                    _fmt_num(r.get("d1"), 1) if r.get("d1") is not None else "—",
                    _fmt_num(r.get("d5"), 1) if r.get("d5") is not None else "—",
                    _fmt_num(r.get("d20"), 1) if r.get("d20") is not None else "—",
                    _arrow(r.get("rel_spy_1d")),
                )
            )
        if sec.get("migration"):
            lines.append("迁移: %s" % sec["migration"])
    lines.append("")

    # ③
    lines.append("## ③ 单腿 Call 候选卡  [源:Polygon 链 + workstation]")
    lines.append("规则:`%s`" % calls.get("rule", ""))
    if calls.get("note"):
        lines.append("_%s_" % calls["note"])
    cards = calls.get("cards") or []
    if not cards:
        lines.append("筛后 **0** 张(门槛未过或数据源 BLOCKED)。")
        for r in (calls.get("near_miss") or [])[:3]:
            lines.append(
                "- near %s %s %sC mid=%s 价差=%s%% OI=%s IVR=%s src=%s"
                % (
                    r.get("ul"),
                    r.get("expiry"),
                    _fmt_num(r.get("K"), 0),
                    _fmt_num(r.get("mid"), 2),
                    _fmt_num(r.get("spread_pct"), 1),
                    r.get("oi"),
                    _fmt_num(r.get("ivr"), 1),
                    r.get("source"),
                )
            )
    else:
        for r in cards:
            be = r.get("be")
            be_pct = r.get("be_pct")
            lines.append("- **%s %s %sC**" % (r.get("ul"), r.get("expiry"), _fmt_num(r.get("K"), 0)))
            lines.append(
                "  mid $%s · 价差 %s%% · IVR %s · OI %s"
                % (
                    _fmt_num(r.get("mid"), 2),
                    _fmt_num(r.get("spread_pct"), 1),
                    _fmt_num(r.get("ivr"), 1),
                    r.get("oi"),
                )
            )
            if r.get("oi_delta") is not None:
                lines.append("  昨 OI %+s" % r["oi_delta"])
            lines.append(
                "  盈亏平衡 %s (%s%%) · 灯:%s"
                % (
                    _fmt_num(be, 1),
                    _fmt_num(be_pct, 1) if be_pct is not None else "—",
                    r.get("lights") or "—",
                )
            )
    lines.append("")

    # ④
    lines.append("## ④ workstation 读数  [源:8620]")
    wi = (ws or {}).get("items") or {}
    if not (ws or {}).get("ok"):
        lines.append("**BLOCKED** · %s" % ((ws or {}).get("error") or "8620 down"))
    else:
        lines.append(
            "gamma_flip %s · net_gex %sM/1%% · IVP %s · VRP20 %s · IVR %s"
            % (
                _fmt_num(wi.get("gamma_flip"), 2),
                _fmt_num(wi.get("net_gex"), 1),
                _fmt_num(wi.get("ivp"), 1),
                _fmt_num(wi.get("vrp20"), 1),
                _fmt_num(wi.get("ivr"), 1),
            )
        )
        lines.append(
            "spot %s %s · date %s · source=%s"
            % (wi.get("underlying"), _fmt_num(wi.get("spot"), 2), wi.get("date"), wi.get("source"))
        )
        if str(wi.get("source") or "").startswith("synthetic"):
            lines.append("_合成链 · 非真盘 GEX——数字可看结构,决策勿当真盘_")
    lines.append("")

    # ⑤
    lines.append("## ⑤ 事件赔率 + 隔夜要闻  [源:Polymarket + DS 缩编]")
    if not odds:
        lines.append("- 赔率:无")
    else:
        for o in odds[:8]:
            if o.get("ok") is False and o.get("error"):
                lines.append("- 赔率 BLOCKED: %s" % o["error"]
                )
                continue
            title = (
                o.get("q") or o.get("title") or o.get("question") or o.get("name")
                or o.get("market") or o.get("event") or o.get("label")
            )
            prob = o.get("prob") or o.get("yes") or o.get("price") or o.get("odds") or o.get("value")
            if prob is None and isinstance(o.get("implied"), list) and o["implied"]:
                try:
                    prob = float(o["implied"][0])
                except Exception:
                    prob = None
            delta = o.get("delta") or o.get("d_overnight")
            if title is None and o.get("text"):
                lines.append("- %s" % str(o["text"])[:180])
                continue
            if title or prob is not None:
                try:
                    pf = float(prob)
                    pct = pf * 100.0 if 0 <= pf <= 1.0 else pf
                    prob_s = _fmt_num(pct, 1) + "%"
                except Exception:
                    prob_s = str(prob) if prob is not None else ""
                extra = ""
                if delta is not None:
                    try:
                        extra = " (隔夜 %+spt)" % _fmt_num(float(delta), 1)
                    except Exception:
                        extra = " (隔夜 %s)" % delta
                lines.append("- %s %s%s" % (title or "market", prob_s, extra))
            else:
                lines.append("- %s" % json.dumps(o, ensure_ascii=False)[:160])
    lines.append("隔夜要闻(DS ≤5):")
    if not news.get("ok"):
        lines.append("- DS BLOCKED: %s" % (news.get("error") or "?"))
    else:
        for ln in news.get("lines") or []:
            lines.append(ln if ln.startswith("-") else "- " + ln)
    lines.append("")
    lines.append("---")
    lines.append("卡点:FMP_API_KEY + POLYGON_API_KEY(starter)。UW flow 未启用(待拍板)。")
    return "\n".join(lines) + "\n"


def build_morning_battle(date: str, raw_payload: dict | None, *, run_ds: bool = True) -> dict:
    ws = workstation.fetch_workstation()
    oi = oi_probe.fetch_oi_probe()
    sec = sectors.fetch_sector_rotation()
    calls = call_cards.fetch_call_cards(ws)
    odds = odds_news.odds_from_raw(raw_payload)
    if not odds:
        odds = odds_news.fetch_polymarket_live()
    if run_ds:
        news = odds_news.ds_news_digest(json.dumps(raw_payload or {}, ensure_ascii=False))
    else:
        news = {"ok": False, "error": "run_ds=false", "lines": []}
    pack = {"oi": oi, "sectors": sec, "calls": calls, "ws": ws, "odds": odds, "news": news}
    md = render_morning_md(date, pack)
    return {"pack": pack, "markdown": md}


def build_evening_recap(date: str, raw_payload: dict | None, *, ds_lines: list[str] | None = None) -> str:
    """晚报骨架:OI 复盘位 + 日历位 + DS 宏观配菜。"""
    oi = oi_probe.fetch_oi_probe()
    lines = ["# 晚报复盘 · %s (Scout v3)" % date, ""]
    lines.append("## 当日 OI 变化")
    if not oi.get("ok"):
        lines.append("BLOCKED · %s" % oi.get("error"))
    else:
        for r in (oi.get("rows") or [])[:10]:
            lines.append("- %s ΔOI=%s vol=%s" % (r.get("label"), r.get("oi_delta"), r.get("volume")))
    lines.append("")
    lines.append("## 候选卡命中回看")
    lines.append("_待晨报 cards 落盘后对账(v3.1)_")
    lines.append("")
    lines.append("## 明日日历")
    # from raw FDA etc
    for block in (raw_payload or {}).get("results") or []:
        if block.get("source") in ("fda_press",) and block.get("ok"):
            for it in (block.get("items") or [])[:5]:
                if isinstance(it, dict):
                    lines.append("- FDA: %s" % (it.get("title") or it.get("text") or it))
                else:
                    lines.append("- FDA: %s" % it)
    lines.append("")
    lines.append("## DS 宏观异动(≤5)")
    if ds_lines:
        for ln in ds_lines[:5]:
            lines.append(ln if ln.startswith("-") else "- " + ln)
    else:
        lines.append("- (无)")
    lines.append("")
    return "\n".join(lines) + "\n"
