#!/usr/bin/env python3
"""scout_agent.py —— Scout Agent v3.3(DS JSON → review/编译 → HTML/卡片)

流水线:
  fetchers(含 ^spx/^ndq/^vix) → raw → 补齐 indices
  → DeepSeek JSON 决策官(Ollama deepseek-v4-pro:cloud, think=false)
  → review/编译(二选一或双跑对照):
       A) GLM 5.2 直连 8501 /v1/chat/completions
       B) b11 STUDIO·EXPANDED 大底座:8515 /gateway/task/expanded → 8501
          (与 grid_workbench_b11 EXPANDED 同链:验证+GLM substrate+Aster 校验接纳)
  → briefs(.md/.html/.json) + console 双 lane + aether_scout_brief(OPTION,含 indices)

硬约束:T+0 单腿 CALL 默认;禁多腿;禁编权利金;候选锚定证据。
禁写 workbench-b11 / cloud 生产记忆;expanded memory_node 默认 scout-review。
"""
from __future__ import annotations
import argparse, datetime, html, json, os, re, sys, urllib.error, urllib.request
from pathlib import Path

import fetchers

_HERE = Path(__file__).resolve().parent


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
# b11 workbench UI — /gateway/task/expanded 代签 grid_verification(同 STUDIO·EXPANDED)
WB = os.getenv("WORKBENCH_URL", "http://127.0.0.1:8515").rstrip("/")
GLM_MODEL = os.getenv("GLM_MODEL", "glm-5.2:cloud")
CONSOLE = os.getenv("CONSOLE_URL", "http://localhost:8610").rstrip("/")
CONSOLE_KEY = os.getenv("CONSOLE_KEY", "").strip()
OWS = os.getenv("OWS_URL", "http://localhost:8620").rstrip("/")
OUT = os.getenv("SCOUT_OUT", str(_HERE))
# 非生产记忆 node —— 禁止 workbench-b11 / cloud-glm52 / cloud-kimi
EXPANDED_MEMORY_NODE = os.getenv("SCOUT_EXPANDED_MEMORY_NODE", "scout-review").strip() or "scout-review"
# 默认终稿 = B · EXPANDED(GLM-5.2);Aster integrate 永久驳回(Lyra 2026-08-05)
DEFAULT_REVIEW = "expanded"
SKIP_ASTER_INTEGRATE = os.getenv("SCOUT_SKIP_ASTER", "1").strip() not in ("0", "false", "no")


def _ds_via_ollama() -> bool:
    return "11434" in DS_BASE or (
        DS_BASE.endswith("/v1") and "deepseek.com" not in DS_BASE
    )


def _http(url, body=None, headers=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method="POST" if data else "GET",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def fetch_workstation_state():
    try:
        dates = _http(OWS + "/api/dates", timeout=5)
        if not dates:
            return None
        d = _http(OWS + "/api/day/" + dates[-1], timeout=5)
        ws = {
            "date": dates[-1],
            "underlying": d["snap"]["underlying"],
            "spot": d["snap"]["spot"],
            "net_gex": d["gex"]["net_gex_musd_per_1pct"],
            "gamma_flip": d["gex"]["gamma_flip"],
            "ivp": d["features"]["ivp"],
            "vrp": d["features"]["vrp20"],
            "source": d["snap"].get("source"),
        }
        if str(ws["source"] or "").startswith("synthetic"):
            print(
                "[scout] workstation 仅合成演示数据(%s)——不作数,不喂 DS"
                % ws["source"]
            )
            return None
        return ws
    except Exception as e:
        print("[scout] workstation(:8620) 不可达:", e)
        return None


def yesterday_raw(today):
    try:
        rawdir = os.path.join(OUT, "raw")
        cand = [f for f in os.listdir(rawdir) if f.endswith(".json") and f[:10] < today]
        if cand:
            last_day = max(f[:10] for f in cand)
            pick = max(
                (f for f in cand if f[:10] == last_day),
                key=lambda f: os.path.getmtime(os.path.join(rawdir, f)),
            )
            return json.load(open(os.path.join(rawdir, pick), encoding="utf-8"))
    except Exception:
        pass
    return None


def summarize_indices(items):
    """items → {SP500:{close,date,proxy,source}, NASDAQ:..., VIX:...}"""
    out = {}
    for it in items or []:
        name = str(it.get("name") or "").upper()
        if name not in ("SP500", "NASDAQ", "VIX"):
            continue
        close = it.get("Close") or it.get("close") or it.get("CLOSE")
        date = it.get("Date") or it.get("date") or it.get("DATE")
        try:
            close_f = float(close) if close is not None else None
        except (TypeError, ValueError):
            close_f = None
        row = {
            "close": close_f,
            "date": date,
            "proxy": it.get("proxy"),
            "source": it.get("source"),
            "note": it.get("note"),
        }
        for k in ("close_loc", "tape_flag", "chg_pct", "open", "high", "low"):
            if it.get(k) is not None and it.get(k) != "":
                row[k] = it.get(k)
        out[name] = row
    return out


def ensure_indices(payload: dict) -> dict:
    """旧 raw / --skip-fetch 可能无 indices → 现场补采,堵住 Aether VIX「缺失」。
    有 Alpaca key 时优先 alpaca 源(SPY/QQQ/VIXY),不用旧 stooq/yahoo 缓存挡道。"""
    results = list(payload.get("results") or [])
    idx = next((r for r in results if r.get("source") == "indices"), None)
    key, _sec = fetchers._load_alpaca_keys()
    if idx and idx.get("ok") and idx.get("items"):
        snap = summarize_indices(idx["items"])
        srcs = {str(it.get("source") or "") for it in idx["items"]}
        vix_ok = snap.get("VIX", {}).get("close") is not None
        # 有 Alpaca 则要求源含 alpaca;否则有 VIX 即可复用
        if vix_ok and ((not key) or ("alpaca" in srcs)):
            return snap
    print("[scout] indices 缺失/非 Alpaca → 现场补采 fetch_indices")
    fresh = fetchers.fetch_indices()
    replaced = False
    for i, r in enumerate(results):
        if r.get("source") == "indices":
            results[i] = fresh
            replaced = True
            break
    if not replaced:
        results.append(fresh)
    payload["results"] = results
    if "skips" in payload:
        payload["skips"] = list(payload.get("skips") or []) + list(fetchers.SKIPS)
    snap = summarize_indices(fresh.get("items") or [])
    print(
        "[scout] indices ok=%s VIX=%s SP500=%s NASDAQ=%s"
        % (
            fresh.get("ok"),
            (snap.get("VIX") or {}).get("close"),
            (snap.get("SP500") or {}).get("close"),
            (snap.get("NASDAQ") or {}).get("close"),
        )
    )
    return snap


def _hedge_ammo(raw):
    """从 raw.results 抽出对冲判断弹药(引擎实测),单独喂 DS 防漏读。"""
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
    """风险中/高且 DS 漏腿时:用引擎实测数字机械补 1-2 条(禁编报价)。"""
    ammo = _hedge_ammo(raw if isinstance(raw, dict) else {"results": raw or []})
    picks = []
    # 优先:GLD/SLV 强势或冲高回落后的避险延续;OXY/USO 仅当自身异动明显
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


def ensure_hedge(data, raw=None):
    """对冲铁律硬闸:hedge 段永不空白;风险中/高缺腿 → 引擎实测补腿。"""
    if not isinstance(data, dict):
        return data
    hd = data.get("hedge")
    if not isinstance(hd, dict):
        data["hedge"] = {
            "distribution_risk": "低",
            "basis": "DS 未输出 hedge 段——按铁律响亮补位为低,待复核",
            "legs": [],
            "note": "原稿缺 hedge;已禁止「什么都不写」",
        }
        print("[scout] hedge 段缺失 → 响亮补位")
        hd = data["hedge"]
    risk = str(hd.get("distribution_risk") or "").strip() or "低"
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
            tag = "【引擎补位】DS 风险%s 但漏腿——已用 hedge_assets/indices 实测补 %d 条,待复核" % (
                risk, len(filled))
            hd["note"] = ((hd.get("note") or "") + " " + tag).strip()
            print("[scout]", tag)
        else:
            warn = "【响亮】风险%s 但 legs 为空且引擎无可用对冲读数——违反对冲铁律,待复核" % risk
            hd["note"] = ((hd.get("note") or "") + " " + warn).strip()
            print("[scout]", warn)
    data["hedge"] = hd
    return data


def build_trading_prompt(raw, ws, yday, indices_snap):
    idx_line = json.dumps(indices_snap, ensure_ascii=False) if indices_snap else "无"
    ammo = _hedge_ammo(raw)
    ammo_line = json.dumps(ammo, ensure_ascii=False)[:3500]
    return f"""你是交易台的首席决策官。开盘在即,基于隔夜数据给出清晰的分析作业
(这是给交易员参考的分析,交易员自己拍板执行,不是自动下单)。
观察宇宙 = S&P 500 与 Nasdaq 成分池(不是 SPY/QQQ 两只 ETF)。

【指数实读(优先引用;有 close 不得写 VIX/指数「缺失」)】
{idx_line}

【对冲弹药·引擎实测(数字出引擎,解读归你;冲高回落=日高破昨收且 close_loc<0.4)】
{ammo_line}

隔夜采集:{json.dumps(raw, ensure_ascii=False)[:4500]}
工作站读数(GEX/特征):{json.dumps(ws, ensure_ascii=False) if ws else "工作站无可用实弹数据(不可达或仅合成数据),基于隔夜数据判断"}
昨日采集(对比用):{json.dumps(yday, ensure_ascii=False)[:1500] if yday else "无"}

交易风格偏置(硬约束):交易员主做 T+0 单腿 CALL,当日了结。
- 策略默认形态 = 单腿 CALL,到期选 0DTE 或最近可用到期,必须给 t0_exit(当日平仓纪律)
- PUT 仅当看空证据明确时才提,并在 evidence 写清依据;禁止多腿组合;禁止编造权利金/报价
候选铁律:每个候选必须锚定隔夜采集中的具体条目(EDGAR/FDA/赔率/指数与宏观读数),
逐条给出处;无证据则 candidates 留空并填 no_candidate_reason;禁止凭训练记忆点名。
对冲铁律(hedge 段永不空白——"没信号什么都不写"从此非法):
- 必须用上面【对冲弹药】里的 close_loc/tape_flag/fear_greed/hedge_assets 实测数字写
  distribution_risk + basis(禁止只凭感觉)
- 风险 中/高 → 必须给 1-2 条对冲腿(仅 GLD/SLV/OXY/USO 池,单腿 call 优先,
  T+0 纪律照旧,evidence 锚定上述读数,禁编报价);池内无候选不是空白的理由
- 风险 低 → note 写明为何暂不需对冲(这也是内容,不许留空)

只输出一个 JSON 对象——不要 markdown、不要代码围栏、不要 JSON 之外的任何文字。schema:
{{"macro": {{"sp500_bias": "看涨|看跌|中性震荡", "nasdaq_bias": "看涨|看跌|中性震荡",
  "confidence": "高|中|低", "logic": "必须引用 indices 中的 VIX/SP500/NASDAQ close(若有);收益率/赔率",
  "key_levels": "大盘关键位(无实弹 GEX 时如实写依据)",
  "vix": "有指数实读则填数字字符串,否则写缺失"}},
 "candidates": [{{"ticker": "", "direction": "call|put",
   "evidence": [{{"source": "edgar|fda|polymarket|indices|macro", "item": "条目摘要", "why": "为何构成驱动"}}],
   "key_levels": "该标的阻力/支撑及依据",
   "strategy": {{"type": "单腿 call", "strike_logic": "行权价选择逻辑(不编报价)",
     "expiry": "0DTE|本周五|最近到期", "entry_condition": "入场触发条件",
     "stop": "止损条件", "abandon": "作废条件", "t0_exit": "当日平仓纪律"}}}}],
 "no_candidate_reason": "candidates 为空时的证据核查结论,否则空串",
 "hedge": {{"distribution_risk": "高|中|低", "basis": "引用 indices/fear_greed/hedge_assets 读数的依据",
   "legs": [{{"ticker": "GLD|SLV|OXY|USO", "direction": "call|put",
     "evidence": [{{"source": "hedge_assets|fear_greed|indices|macro", "item": "读数", "why": "为何对冲"}}],
     "strategy": {{"type": "单腿 call", "strike_logic": "", "expiry": "0DTE|本周五|最近到期",
       "entry_condition": "", "stop": "", "abandon": "", "t0_exit": ""}}}}],
   "note": "风险低暂不对冲时写明依据;永不空白"}},
 "data_gaps": [{{"item": "", "status": "", "handling": ""}}],
 "conclusion": "一句话结论"}}
禁止"具体视情况而定""谨慎操作"等无效废话。全部值用中文。
data_gaps 里仅当【指数实读】确实无 VIX close 时才写 VIX 缺失。"""


def build_evening_prompt(raw, yday, indices_snap):
    return f"""你是交易台参谋。写今日收盘复盘 + 明日弹药,给交易员看:
1. 今日要闻与并购/FDA/事件催化(带出处)
2. 隔夜→今日的赔率变化(Polymarket)
3. 明日日历(FDA/到期/财报/事件)
4. 明日值得盯的方向与关键位(分析,非指令)
5. 风险雷达(黑天鹅/机构拉高出货排查,永不留空):逐项核对——indices 的
   tape_flag(冲高回落即拉高出货典型日线形)与 close_loc、fear_greed 贪婪极值、
   hedge_assets(GLD/SLV/OXY/USO)异动、polymarket bucket=event 的赔率突变;
   命中则响亮点名并给对冲候选方向(GLD/SLV/OXY/USO),未命中则明写"今日未见"
指数实读:{json.dumps(indices_snap, ensure_ascii=False) if indices_snap else "无"}
今日采集:{json.dumps(raw, ensure_ascii=False)[:6000]}
昨日对比:{json.dumps(yday, ensure_ascii=False)[:1500] if yday else "无"}
用 markdown,严格以 ## 分节(要闻催化/赔率变化/明日日历/明日方向/风险雷达),
每节内用短段落或列表,不要糊成整段。用中文,给数字给出处,不写废话。"""


def ds_call(prompt):
    if not DS_KEY:
        raise SystemExit(
            "[scout] DEEPSEEK_API_KEY 未配置。\n"
            "  默认 Ollama Cloud: DEEPSEEK_BASE=http://127.0.0.1:11434/v1\n"
            "  DEEPSEEK_MODEL=deepseek-v4-pro:cloud DEEPSEEK_API_KEY=ollama"
        )
    if DS_BASE.endswith("/v1"):
        url = DS_BASE + "/chat/completions"
    elif "deepseek.com" in DS_BASE:
        url = DS_BASE.rstrip("/") + "/chat/completions"
    else:
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
        raise SystemExit(
            "[scout] DS 空正文 model=%s finish=%s"
            % (DS_MODEL, (r.get("choices") or [{}])[0].get("finish_reason"))
        )
    return text


def _extract_json(text):
    t = text or ""
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        try:
            return json.loads(t[i : j + 1])
        except Exception:
            return None
    return None


def build_review_prompt(
    mode: str, ds_draft: str, data, indices_snap, *, reviewer: str
) -> str:
    idx = json.dumps(indices_snap, ensure_ascii=False) if indices_snap else "无"
    if mode == "morning":
        must = (
            "上游已是 JSON 结构化晨会单。你输出更清晰的 Markdown 终稿给 Lyra:\n"
            "- 保留个股卡结构;默认 T+0 单腿 CALL;禁多腿;禁编权利金/假 $ 报价\n"
            "- 【指数实读】有 VIX close 时禁止写「VIX 缺失」,必须引用数字\n"
            "- SPY/QQQ 仅大盘环境;主菜=个股\n"
            "- synthetic GEX 不得洗成真盘\n"
            "- 无候选时诚实写观望理由,禁止编造个股卡(含 PLTR 等样例)\n"
            "- hedge 段永不空白:保留 distribution_risk/basis/legs 或 note"
        )
    else:
        must = "输出四段 Markdown 终稿;禁止补编采集中没有的数字。"
    struct = json.dumps(data, ensure_ascii=False)[:9000] if data else ds_draft[:9000]
    return f"""你是 Scout 流水线的 review / 编译官({reviewer}),不是首席决策官。
{must}
指数实读(权威):{idx}
—— DeepSeek 结构化原稿 ——
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
        "client_context": "scout_review · expanded GLM-5.2 · skip_aster_integrate",
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
        print(
            "[scout] EXPANDED review/编译完成 %d 字符 substrate=%s orch=%s"
            % (len(final), meta.get("substrate"), meta.get("orchestrator"))
        )
        return {"text": final, "meta": meta}
    except Exception as e:
        print("[scout] EXPANDED review 失败(%s)→ 降级用 DS 原稿(响亮)" % e)
        return {
            "text": ds_draft,
            "meta": {"error": str(e), "via": "fallback_ds", "memory_node": EXPANDED_MEMORY_NODE},
        }


# ---- 渲染层:结构照抄 brief sample hedge;色板=白底灰框(禁全黑偷懒) ----
# 权威 UI 文件(已从 CloudDocs 样例结构生成,仅替换色板 token):
_UI_BRIEF = _HERE / "briefs" / "_ui_brief_sample_hedge_paper.html"


def _load_brief_css() -> str:
    raw = _UI_BRIEF.read_text(encoding="utf-8")
    m = re.search(r"<style>(.*?)</style>", raw, re.S)
    if not m:
        raise RuntimeError("UI brief 缺 <style>: %s" % _UI_BRIEF)
    css = m.group(1)
    if "#07090e" in css or "rgba(17,22,34" in css:
        raise RuntimeError("UI CSS 仍是全黑样板——拒绝渲染")
    if "#e6e6e2" not in css or "#ffffff" not in css:
        raise RuntimeError("UI CSS 不是白底灰框")
    return css


BRIEF_CSS = _load_brief_css()



def _esc(x):
    return html.escape(str(x if x is not None else ""))


def _cand_card(c, tag, badge="SCOUT"):
    d = (c.get("direction") or "call").lower()
    st = c.get("strategy") or {}
    evs = "".join(
        '<div class="ev"><div class="src">%s</div><div>%s</div><div class="why">%s</div></div>'
        % (_esc(e.get("source", "")), _esc(e.get("item", "")), _esc(e.get("why", "")))
        for e in (c.get("evidence") or [])
    ) or '<div class="ev">(无证据条目——按铁律本卡不应存在)</div>'
    rows = [
        ("形态", st.get("type")),
        ("行权价逻辑", st.get("strike_logic")),
        ("到期", st.get("expiry")),
        ("入场条件", st.get("entry_condition")),
        ("止损", st.get("stop")),
        ("作废条件", st.get("abandon")),
        ("T+0 平仓", st.get("t0_exit")),
        ("关键位", c.get("key_levels")),
    ]
    kvs = "".join(
        '<div class="kv"><b>%s</b><span>%s</span></div>' % (l, _esc(v))
        for l, v in rows
        if v
    )
    return (
        '<div class="card"><span class="badge">%s %s</span>'
        '<div class="tick"><span class="sym">%s</span><span class="pill%s">%s</span></div>%s'
        "<details><summary>展开解析(证据出处)</summary>%s</details></div>"
        % (
            _esc(badge),
            _esc(tag),
            _esc((c.get("ticker") or "?").upper()),
            " put" if d == "put" else "",
            d.upper(),
            kvs,
            evs,
        )
    )


def _fmt_idx(snap, key):
    v = (snap or {}).get(key) or {}
    c = v.get("close")
    if c is None:
        return "缺失"
    try:
        return ("%.2f" % float(c)).rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(c)


def _render_structured(date, data, indices_snap=None):
    m = data.get("macro") or {}
    cands = data.get("candidates") or []
    gaps = data.get("data_gaps") or []
    hd = data.get("hedge") or {}
    risk = hd.get("distribution_risk") or "—"
    rc = {"高": "var(--red)", "中": "var(--gold)", "低": "var(--grn)"}.get(risk, "var(--dim)")
    vix = _fmt_idx(indices_snap, "VIX")
    if vix == "缺失" and m.get("vix") not in (None, "", "缺失"):
        vix = str(m.get("vix"))
    out = [
        '<div class="banner"><b>晨会交易任务单</b><span class="num">%s</span>'
        "<span>SP500 <b>%s</b></span><span>NASDAQ <b>%s</b></span>"
        "<span>VIX <b class=\"num\">%s</b></span><span>置信 <b>%s</b></span>"
        '<span>出货风险 <b style="color:%s">%s</b></span></div>'
        % (
            _esc(date),
            _esc(m.get("sp500_bias", "—")),
            _esc(m.get("nasdaq_bias", "—")),
            _esc(vix),
            _esc(m.get("confidence", "—")),
            rc,
            _esc(risk),
        )
    ]
    out.append(
        '<section><h2>一 · 大盘方向</h2><div class="card">'
        '<div class="kv"><b>逻辑</b><span>%s</span></div>'
        '<div class="kv"><b>关键位</b><span>%s</span></div>'
        '<div class="kv"><b>指数实读</b><span class="num">SPX %s · NDQ %s · VIX %s</span></div>'
        "</div></section>"
        % (
            _esc(m.get("logic", "")),
            _esc(m.get("key_levels", "")),
            _esc(_fmt_idx(indices_snap, "SP500")),
            _esc(_fmt_idx(indices_snap, "NASDAQ")),
            _esc(vix),
        )
    )
    if cands:
        out.append(
            '<section><h2>二 · 池内候选(默认形态:T+0 单腿 CALL)</h2>%s</section>'
            % "".join(_cand_card(c, date) for c in cands)
        )
    else:
        out.append(
            '<section><h2>二 · 池内候选</h2><div class="empty">今日池内无事件驱动候选'
            '<br><span style="font-size:var(--f1)">%s</span></div></section>'
            % _esc(data.get("no_candidate_reason", ""))
        )
    # 对冲段永不空白:无 legs 也必须露出评估卡(风险低写 note;中/高缺腿响亮)
    legs = hd.get("legs") or []
    hcard = (
        '<div class="card"><div class="kv"><b>风险评估</b>'
        '<span style="color:%s">%s</span></div>'
        '<div class="kv"><b>依据</b><span>%s</span></div>%s</div>'
        % (
            rc,
            _esc(risk),
            _esc(hd.get("basis") or "（依据空——违反对冲铁律）"),
            (
                '<div class="kv"><b>说明</b><span>%s</span></div>'
                % _esc(hd.get("note") or ("风险低暂不对冲" if risk == "低" and not legs else ""))
            )
            if (hd.get("note") or (risk == "低" and not legs))
            else "",
        )
    )
    out.append(
        '<section><h2>三 · 对冲(拉高出货/黑天鹅雷达)</h2>%s%s</section>'
        % (hcard, "".join(_cand_card(l, date, "HEDGE") for l in legs))
    )
    if gaps:
        out.append(
            '<section><h2>四 · 数据缺失与矛盾标注</h2><div class="card"><table>'
            "<tr><th>项目</th><th>状态</th><th>处理</th></tr>%s</table></div></section>"
            % "".join(
                "<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
                % (
                    _esc(g.get("item")),
                    _esc(g.get("status")),
                    _esc(g.get("handling")),
                )
                for g in gaps
            )
        )
    if data.get("conclusion"):
        out.append(
            '<section><h2>五 · 结论</h2><div class="card">%s</div></section>'
            % _esc(data.get("conclusion"))
        )
    return "".join(out)


def _md_fallback(text):
    out, buf = [], []

    def flush():
        if buf:
            out.append("<p>%s</p>" % "<br>".join(buf))
            buf.clear()

    for ln in (text or "").splitlines():
        t = ln.strip()
        if not t or t == "---":
            flush()
            continue
        if t.startswith("#"):
            flush()
            out.append("<h2>%s</h2>" % _esc(t.lstrip("#").strip()))
        else:
            e = _esc(t)
            e = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", e)
            buf.append(e)
    flush()
    return '<section><div class="card">%s</div></section>' % "".join(out)


def render_brief_html(date, mode, data, raw_text, indices_snap=None):
    body = (
        _render_structured(date, data, indices_snap)
        if data
        else _md_fallback(raw_text)
    )
    return (
        '<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"/>'
        '<meta name="viewport" content="width=device-width,initial-scale=1"/>'
        "<title>SCOUT · %s · %s</title><style>%s</style></head><body>"
        "<header><h1>SCOUT</h1><span class=\"sub\">%s · %s · 参谋作业,Lyra 拍板</span></header>"
        "%s<footer>build scout v3.4 · DS JSON → EXPANDED(GLM-5.2,skip Aster) · hedge · "
        "UI=sample hedge结构+白底灰框 · 渲染:_render_structured/_cand_card</footer></body></html>"
        % (mode.upper(), _esc(date), BRIEF_CSS, mode, _esc(date), body)
    )


def archive_console(title, ds_draft, glm_final, mode, data, *, expanded_final=None):
    ds_id = glm_id = None
    if not CONSOLE_KEY:
        print("[scout] CONSOLE_KEY 未配置 → 跳过 console 存档")
        return None, None
    try:
        ds_doc = (
            "[DS 决策官作业·JSON] " + json.dumps(data, ensure_ascii=False)[:8000]
            if data
            else "[DS 决策官作业,存档] " + ds_draft[:8000]
        )
        t1 = _http(
            CONSOLE + "/api/tasks",
            {
                "workspace": "trade",
                "title": title + " · DS原稿",
                "owner_node": "deepseek_lane",
                "risk_level": "read",
                "io_contract": ds_doc,
            },
            {"X-Console-Key": CONSOLE_KEY},
        )
        ds_id = t1.get("task_id")
        print("[scout] console DS#%s" % ds_id)
        primary = expanded_final or glm_final
        label = "EXPANDED终稿" if expanded_final else "GLM终稿"
        t2 = _http(
            CONSOLE + "/api/tasks",
            {
                "workspace": "trade",
                "title": title + " · " + label,
                "owner_node": "glm_lane",
                "risk_level": "read",
                "deps": [ds_id] if ds_id else [],
                "io_contract": (
                    "[%s review 编译终稿,存档] mode=%s\n" % (label, mode)
                    + (primary or "")[:8000]
                ),
            },
            {"X-Console-Key": CONSOLE_KEY},
        )
        glm_id = t2.get("task_id")
        print("[scout] console %s#%s" % (label, glm_id))
    except Exception as e:
        print("[scout] console 存档失败(%s)→ 仅本地落盘" % e)
    return ds_id, glm_id


def write_briefs(
    title,
    primary_final,
    ds_draft,
    date,
    mode,
    data,
    indices_snap,
    *,
    glm_final="",
    expanded_final="",
    expanded_meta=None,
    primary_label="review",
):
    bdir = os.path.join(OUT, "briefs")
    os.makedirs(bdir, exist_ok=True)
    bp = os.path.join(bdir, "%s-%s.md" % (date, mode))
    sections = ["# %s\n" % title]
    if expanded_final:
        meta = expanded_meta or {}
        sections.append(
            "## EXPANDED 终稿(b11 STUDIO·EXPANDED 大底座 review/编译)\n\n"
            "via=%s · substrate=%s · orch=%s · memory_node=%s\n\n%s\n"
            % (
                meta.get("via"),
                meta.get("substrate"),
                meta.get("orchestrator"),
                meta.get("memory_node"),
                expanded_final.strip(),
            )
        )
    if glm_final:
        sections.append("## GLM 直连终稿(8501 /v1 · %s)\n\n%s\n" % (GLM_MODEL, glm_final.strip()))
    if not expanded_final and not glm_final:
        sections.append("## %s 终稿\n\n%s\n" % (primary_label, (primary_final or "").strip()))
    sections.append("---\n\n## DS 原稿(A/B 对照 · 勿当终稿)\n\n%s\n" % ds_draft.strip())
    text = "\n".join(sections)
    with open(bp, "w", encoding="utf-8") as f:
        f.write(text)
    hp = os.path.join(bdir, "%s-%s.html" % (date, mode))
    with open(hp, "w", encoding="utf-8") as f:
        f.write(
            render_brief_html(
                date, mode, data, primary_final or ds_draft, indices_snap
            )
        )
    if data is not None:
        with open(os.path.join(bdir, "%s-%s.json" % (date, mode)), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "data": data,
                    "indices": indices_snap,
                    "review": {
                        "primary": primary_label,
                        "glm_chars": len(glm_final or ""),
                        "expanded_chars": len(expanded_final or ""),
                        "expanded_meta": expanded_meta or {},
                    },
                },
                f,
                ensure_ascii=False,
                indent=1,
            )
    if mode == "morning":
        with open(os.path.join(bdir, "%s_morning_task.md" % date), "w", encoding="utf-8") as f:
            f.write(text)
        with open(os.path.join(bdir, "%s-morning-final.md" % date), "w", encoding="utf-8") as f:
            f.write("# %s\n\n%s\n" % (title, (primary_final or "").strip()))
        if glm_final:
            with open(
                os.path.join(bdir, "%s-morning-final-glm.md" % date), "w", encoding="utf-8"
            ) as f:
                f.write("# %s · GLM直连\n\n%s\n" % (title, glm_final.strip()))
        if expanded_final:
            with open(
                os.path.join(bdir, "%s-morning-final-expanded.md" % date),
                "w",
                encoding="utf-8",
            ) as f:
                f.write(
                    "# %s · EXPANDED\n\n%s\n"
                    % (title, expanded_final.strip())
                )
        if glm_final and expanded_final:
            with open(
                os.path.join(bdir, "%s-morning-ab-compare.md" % date),
                "w",
                encoding="utf-8",
            ) as f:
                f.write(
                    "# Scout review A/B · %s\n\n"
                    "同一份 DS JSON 原稿 → 两边独立 review/编译(无假卡样例)。\n\n"
                    "## A · GLM 直连 (`%s`)\n\n%s\n\n---\n\n"
                    "## B · b11 STUDIO·EXPANDED (`8515/gateway/task/expanded`)\n\n%s\n"
                    % (
                        date,
                        GLM_MODEL,
                        glm_final.strip(),
                        expanded_final.strip(),
                    )
                )
    print("[scout] 落盘:", bp, "+", hp)
    return bp


def emit_aether(
    date,
    mode,
    title,
    body,
    bp,
    ws=None,
    *,
    ds_draft="",
    glm_final="",
    expanded_final="",
    expanded_meta=None,
    primary_label="review",
    ds_task_id=None,
    glm_task_id=None,
    indices_snap=None,
    data=None,
):
    vix = (indices_snap or {}).get("VIX") or {}
    payload = {
        "date": date,
        "mode": mode,
        "title": title,
        "body": body,
        "glm_final": glm_final or "",
        "expanded_final": expanded_final or "",
        "expanded_meta": expanded_meta or {},
        "primary_review": primary_label,
        "ds_draft": ds_draft or "",
        "via": "scout_v3_4_ds_expanded",
        "brief_path": bp,
        "workstation": ws,
        "console_ds_task": ds_task_id,
        "console_glm_task": glm_task_id,
        "pipeline": "DS JSON→EXPANDED(GLM-5.2 skip Aster)·hedge铁律",
        "review_default": DEFAULT_REVIEW,
        "skip_aster_integrate": SKIP_ASTER_INTEGRATE,
        "indices": indices_snap or {},
        "vix": vix.get("close"),
        "vix_date": vix.get("date"),
        "structured": data,
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
            print(
                "[scout] aether OPTION emit",
                "ok" if 200 <= resp.status < 300 else resp.status,
                "VIX=",
                vix.get("close"),
            )
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print("[scout] aether emit 失败(响亮):", e)


def run_pipeline(
    mode, payload, today, yday, ws=None, indices_snap=None, review="both"
):
    indices_snap = indices_snap or {}
    if mode == "morning":
        title = "Scout 晨会交易任务单 · " + today
        print("[scout] DS 决策官(JSON)…")
        ds_draft = ds_call(build_trading_prompt(payload, ws, yday, indices_snap))
        data = _extract_json(ds_draft)
        if data is None:
            print("[scout] DS 未按 JSON schema 输出——晨会单降级为文本分节渲染(响亮记录)")
        else:
            data = ensure_hedge(data, payload)
    else:
        title = "Scout 晚报复盘 · " + today
        print("[scout] DS 决策官…")
        ds_draft = ds_call(build_evening_prompt(payload, yday, indices_snap))
        data = None

    glm_final = ""
    expanded_final = ""
    expanded_meta = {}
    print("[scout] DS 作业 %d 字符 → review=%s…" % (len(ds_draft), review))
    if review in ("glm", "both"):
        glm_final = glm_review(mode, ds_draft, data, indices_snap)
    if review in ("expanded", "both"):
        er = expanded_review(mode, ds_draft, data, indices_snap)
        expanded_final = er.get("text") or ""
        expanded_meta = er.get("meta") or {}

    # UI/OPTION 主稿:优先可用的 EXPANDED;云端拒发/空稿则回退 GLM(响亮)
    exp_ok = bool(expanded_final) and not str(
        (expanded_meta or {}).get("substrate") or ""
    ).endswith("_error") and not expanded_final.startswith("cloud 不可用")
    if exp_ok and review in ("expanded", "both"):
        primary, primary_label = expanded_final, "expanded"
    else:
        if expanded_final and not exp_ok:
            print("[scout] EXPANDED 不可用 → 主稿改用 GLM(对照文件仍保留两侧)")
        primary, primary_label = glm_final or ds_draft, "glm"

    ds_id, glm_id = archive_console(
        title,
        ds_draft,
        glm_final,
        mode,
        data,
        expanded_final=expanded_final if primary_label == "expanded" else None,
    )
    bp = write_briefs(
        title,
        primary,
        ds_draft,
        today,
        mode,
        data,
        indices_snap,
        glm_final=glm_final,
        expanded_final=expanded_final,
        expanded_meta=expanded_meta,
        primary_label=primary_label,
    )
    emit_aether(
        today,
        mode,
        title,
        primary,
        bp,
        ws=ws,
        ds_draft=ds_draft,
        glm_final=glm_final,
        expanded_final=expanded_final,
        expanded_meta=expanded_meta,
        primary_label=primary_label,
        ds_task_id=ds_id,
        glm_task_id=glm_id,
        indices_snap=indices_snap,
        data=data,
    )
    return bp


POLICY_IO = """Scout Agent 默认流水线(Lyra 拍板 2026-08-05 · 永久)

默认终稿 = B · b11 STUDIO·EXPANDED
  路径: 8515 /gateway/task/expanded → 8501 orchestrator
  substrate: GLM-5.2 (glm52_cloud)
  memory_node: scout-review(禁 workbench-b11 / cloud 生产记忆)
  Aster integrate: 驳回(skip_aster_integrate=true)

上游: DeepSeek JSON 决策官(Ollama deepseek-v4-pro:cloud)
下游: briefs HTML/MD + console 双 lane 存档 + 8501 store kind=aether_scout_brief

硬纪律:
  - hedge 段永不空白(无信号=犯规);中/高须 1-2 腿 GLD/SLV/OXY/USO
  - tape 引擎出数字(chg_pct/close_loc/tape_flag),解读归 DS
  - 禁编权利金;禁假个股卡;T+0 单腿 CALL 默认
  - GLM 直连仅 A/B 对照(--review both),生产默认 --review expanded

调度: com.grid.morning-brief 06:00 / com.grid.evening-brief 21:00(模板在 grid-scout/)
"""


def register_pipeline_policy():
    """把默认 B + 驳回 Aster 写入 8501 store + console(不动 gateway 源码)。"""
    today = datetime.date.today().isoformat()
    payload = {
        "policy_id": "scout-review-b-v1",
        "effective": today,
        "review_default": DEFAULT_REVIEW,
        "skip_aster_integrate": SKIP_ASTER_INTEGRATE,
        "substrate": "glm-5.2",
        "via": "8515/gateway/task/expanded → 8501",
        "memory_node": EXPANDED_MEMORY_NODE,
        "pipeline": "DS JSON→EXPANDED(GLM-5.2 skip Aster)·hedge铁律",
        "hedge_iron_law": True,
        "note": "默认终稿=B EXPANDED;驳回 Aster;GLM 直连仅 A/B",
        "io_contract": POLICY_IO,
    }
    # 8501 store(既有 /store/events,不改 gateway 代码)
    body = {
        "source": "aether",
        "kind": "aether_scout_policy",
        "payload": payload,
    }
    try:
        _http(GW + "/store/events", body, timeout=20)
        print("[scout] 8501 store 已写入 aether_scout_policy")
    except Exception as e:
        print("[scout] 8501 store 政策写入失败(响亮):", e)
        raise

    mission_id = task_id = None
    if not CONSOLE_KEY:
        print("[scout] CONSOLE_KEY 未配置 → 跳过 console 登记")
        return {"store": "ok", "mission_id": None, "task_id": None}

    try:
        m = _http(
            CONSOLE + "/api/missions",
            {
                "workspace": "trade",
                "goal": (
                    "Scout 晨会/晚报 · 默认 EXPANDED(B) review · 驳回 Aster · hedge铁律 "
                    "(policy scout-review-b-v1 · %s)" % today
                ),
            },
            {"X-Console-Key": CONSOLE_KEY},
            timeout=30,
        )
        mission_id = m.get("mission_id") or m.get("id") or m.get("mid")
        print("[scout] console mission#%s" % mission_id)
    except Exception as e:
        print("[scout] console mission 失败(响亮):", e)

    try:
        t = _http(
            CONSOLE + "/api/tasks",
            {
                "workspace": "trade",
                "title": "Scout 默认B · EXPANDED(驳回Aster) · policy scout-review-b-v1",
                "owner_node": "glm_lane",
                "risk_level": "read",
                "io_contract": POLICY_IO
                + "\n\n8501 kind=aether_scout_policy · policy_id=scout-review-b-v1\n"
                + "mission_id=%s\n" % mission_id,
            },
            {"X-Console-Key": CONSOLE_KEY},
            timeout=30,
        )
        task_id = t.get("task_id")
        print("[scout] console task#%s (glm_lane · 政策存档)" % task_id)
    except Exception as e:
        print("[scout] console task 失败(响亮):", e)
        raise

    return {"store": "ok", "mission_id": mission_id, "task_id": task_id, "payload": payload}


def main():
    ap = argparse.ArgumentParser(
        description="Scout Agent v3.4(DS JSON→默认 EXPANDED/驳回Aster)"
    )
    ap.add_argument("--mode", choices=["evening", "morning"], default="evening")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-fetch", action="store_true")
    ap.add_argument(
        "--register-policy",
        action="store_true",
        help="仅登记默认B+驳回Aster到8501 store与console,不跑采集/DS",
    )
    ap.add_argument(
        "--review",
        choices=["glm", "expanded", "both"],
        default=os.getenv("SCOUT_REVIEW", DEFAULT_REVIEW),
        help="review/编译路径:expanded=默认B(驳回Aster) · glm=直连对照 · both=A/B",
    )
    a = ap.parse_args()
    if a.register_policy:
        register_pipeline_policy()
        return
    today = datetime.date.today().isoformat()
    os.makedirs(os.path.join(OUT, "raw"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "briefs"), exist_ok=True)
    raw_path = os.path.join(OUT, "raw", today + ".json")

    if a.skip_fetch and os.path.exists(raw_path):
        payload = json.load(open(raw_path, encoding="utf-8"))
        print("[scout] --skip-fetch 复用", raw_path)
    else:
        results = fetchers.run_all()
        payload = {"results": results, "skips": fetchers.SKIPS}
        if os.path.exists(raw_path):
            raw_path = raw_path.replace(
                ".json", "-" + datetime.datetime.now().strftime("%H%M") + ".json"
            )
        json.dump(
            payload, open(raw_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1
        )
        ok = sum(1 for r in payload["results"] if r["ok"])
        print(
            "[scout] %s 源成功 %d/%d → %s"
            % (today, ok, len(payload["results"]), raw_path)
        )
        for b in payload["results"]:
            if not b["ok"]:
                print("   ✗", b["source"], b.get("error", ""))

    indices_snap = ensure_indices(payload)
    # 把补采后的 payload 写回 today.json,避免下次 skip-fetch 仍无 VIX
    try:
        with open(os.path.join(OUT, "raw", today + ".json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
    except Exception as e:
        print("[scout] 写回 raw 失败(响亮):", e)

    if a.dry_run:
        print("[scout] --dry-run 止步于采集;indices=", indices_snap)
        return

    yday = yesterday_raw(today)
    ws = fetch_workstation_state() if a.mode == "morning" else None
    run_pipeline(
        a.mode,
        payload,
        today,
        yday,
        ws=ws,
        indices_snap=indices_snap,
        review=a.review,
    )


if __name__ == "__main__":
    main()
