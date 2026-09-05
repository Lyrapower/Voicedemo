#!/usr/bin/env python3
"""scout_agent.py —— Scout Agent v3(DS 决策官 + GLM review 编译)

流水线:
  fetchers → raw → DeepSeek 决策官作业 → GLM review/编译终稿
  → briefs/ 落盘 + console 双 lane 存档 + aether_scout_brief(OPTION)

DS = 参谋作业(方向/行权价/策略/放弃 或 晚报复盘四段)
GLM = review/编译官(不改价位、不编造;结构保留;输出终稿给 Lyra)
建议 ≠ 自动下单。A/B:终稿旁保留 DS 原稿。
"""
from __future__ import annotations
import argparse, datetime, json, os, re, sys, urllib.error, urllib.request
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

DS_BASE = os.getenv("DEEPSEEK_BASE", "https://api.deepseek.com").rstrip("/")
DS_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DS_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
GW = os.getenv("GATEWAY_URL", "http://127.0.0.1:8501").rstrip("/")
GLM_MODEL = os.getenv("GLM_MODEL", "glm-5.2:cloud")
CONSOLE = os.getenv("CONSOLE_URL", "http://localhost:8610").rstrip("/")
CONSOLE_KEY = os.getenv("CONSOLE_KEY", "").strip()
OWS = os.getenv("OWS_URL", "http://localhost:8620").rstrip("/")
OUT = os.getenv("SCOUT_OUT", str(_HERE))


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


# ---- reviewer Patch 8:workstation 数据联动 ----
def fetch_workstation_state():
    try:
        dates = _http(OWS + "/api/dates", timeout=5)
        if not dates:
            return None
        d = _http(OWS + "/api/day/" + dates[-1], timeout=5)
        return {
            "date": dates[-1],
            "underlying": d["snap"]["underlying"],
            "spot": d["snap"]["spot"],
            "net_gex": d["gex"]["net_gex_musd_per_1pct"],
            "gamma_flip": d["gex"]["gamma_flip"],
            "ivp": d["features"]["ivp"],
            "vrp": d["features"]["vrp20"],
            "source": d["snap"].get("source"),
        }
    except Exception as e:
        print("[scout] workstation(:8620) 不可达:", e)
        return None


def yesterday_raw(today):
    try:
        prev = [
            f
            for f in sorted(os.listdir(os.path.join(OUT, "raw")))
            if f.endswith(".json") and f < today + ".json"
        ]
        if prev:
            with open(os.path.join(OUT, "raw", prev[-1]), encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def load_raw(today: str, *, skip_fetch: bool) -> tuple[str, dict]:
    raw_dir = os.path.join(OUT, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    today_path = os.path.join(raw_dir, today + ".json")
    if skip_fetch:
        if os.path.exists(today_path):
            with open(today_path, encoding="utf-8") as f:
                print("[scout] --skip-fetch 复用", today_path)
                return today_path, json.load(f)
        files = sorted(
            f for f in os.listdir(raw_dir) if f.endswith(".json") and not f.startswith(".")
        )
        if not files:
            raise SystemExit("[scout] --skip-fetch 但 raw/ 无 json")
        bare = [f for f in files if re.match(r"^\d{4}-\d{2}-\d{2}\.json$", f)]
        pick = bare[-1] if bare else files[-1]
        path = os.path.join(raw_dir, pick)
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        print("[scout] --skip-fetch:今日 raw 缺失 → 复用", path)
        return path, payload
    results = fetchers.run_all()
    payload = {"results": results, "skips": fetchers.SKIPS}
    path = today_path
    if os.path.exists(path):
        path = path.replace(
            ".json", "-" + datetime.datetime.now().strftime("%H%M") + ".json"
        )
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    ok = sum(1 for r in payload["results"] if r["ok"])
    print("[scout] %s 源成功 %d/%d → %s" % (today, ok, len(payload["results"]), path))
    for b in payload["results"]:
        if not b["ok"]:
            print("   ✗", b["source"], b.get("error", ""))
    return path, payload


# ---- DS 决策官 prompt(reviewer Patch 7 四段原样保留 + Patch 8 :8620 真读数) ----
# Patch 7 四段(一个字不删):方向判断+置信度 / 关键行权价 / 具体策略(行权价·到期·最大亏损) / 放弃条件
# Patch 8:晨报先拉 :8620 GEX/gamma_flip/IVP/VRP 真读数喂入下方 JSON,禁止当幻觉忽略
def build_trading_prompt(raw, ws, yday):
    return f"""你是交易台的首席决策官。开盘在即,基于隔夜数据给出清晰的分析作业
(这是给交易员参考的分析,交易员自己拍板执行,不是自动下单)。

主菜=S&P 500 + Nasdaq 个股观察卡(1–3 只)。不是 SPY/QQQ 指数策略卡。
从隔夜采集(EDGAR/FDA/事件/赔率等)挑有催化的成分股;不得无催化硬写固定标的。
:8620 SPY GEX/IVP/VRP 只作「大盘环境」短段(引用真读数),禁止把 SPY/QQQ 写成③具体策略标的,禁止可执行清单以 SPY 为主菜。
字段纪律:无实盘期权报价时标注「无实盘报价 · 仅结构建议」;禁止编造 mid/ask/权利金。
入场只写时间窗与条件(如开盘后 15–30 分钟、站上某逻辑位再考虑),不写假成交价。

隔夜采集:{json.dumps(raw, ensure_ascii=False)[:3500]}
工作站真读数(:8620 · GEX/gamma_flip/IVP/VRP,必须引用做判断,不得当缺失忽略):{json.dumps(ws, ensure_ascii=False) if ws else "工作站不可达,基于隔夜数据判断"}
昨日采集(对比用):{json.dumps(yday, ensure_ascii=False)[:1200] if yday else "无"}

输出顺序(强制):
A. 「大盘环境」(短,≤12 行):只写 Patch 7 之①——方向判断:今日 SPY/QQQ 偏向(看涨/看跌/中性震荡)+ 置信度(高/中/低)+ 逻辑(须引 net_gex/gamma_flip/ivp/vrp)。此处禁止写 SPY/QQQ 买卖期权策略。
B. 「个股观察卡」(正文主体,1–3 只)。每只股票各自完整写出 Patch 7 四段原文骨架(一个字不删字段名):
1. 方向判断:今日偏向(看涨/看跌/中性震荡)+ 置信度(高/中/低)+ 逻辑(个股催化+大盘环境引用)
2. 关键行权价:基于 GEX/OI 或个股逻辑位,今日阻力位与支撑位
3. 具体策略:一种期权策略(如买入 Bull Call Spread / 卖出 Put),
   含具体行权价、到期日(0DTE 或本周五)、最大亏损
   (标的=该个股 ticker,禁止 SPY/QQQ;无链则「无实盘报价 · 仅结构建议」+时间窗入场)
4. 放弃条件:什么情况该策略作废(可含该股逻辑位;大盘失守可作辅条件,但主策略仍是个股)
C. 可执行清单:只列个股卡;若某只缺行权价/放弃条件则标「观察-未齐」,不得用 SPY 策略顶替。
禁止"具体视情况而定""谨慎操作"等无效废话。用中文。
若 workstation source=synthetic-v1,必须在大盘环境/关键行权价处如实标注「合成链,非真盘 GEX」(读数仍须引用)。"""


def build_evening_prompt(raw, yday):
    return f"""你是交易台参谋。写今日收盘复盘 + 明日弹药,给交易员看:
1. 今日要闻与并购/FDA/事件催化(带出处)
2. 隔夜→今日的赔率变化(Polymarket)
3. 明日日历(FDA/到期/财报/事件)
4. 明日值得盯的方向与关键位(分析,非指令)
今日采集:{json.dumps(raw, ensure_ascii=False)[:6000]}
昨日对比:{json.dumps(yday, ensure_ascii=False)[:1500] if yday else "无"}
用中文,给数字给出处,不写废话。"""


def ds_call(prompt):
    if not DS_KEY:
        raise SystemExit(
            "[scout] DEEPSEEK_API_KEY 未配置。\n"
            "  1) platform.deepseek.com 注册取 key,填 .env 或 plist\n"
            "  2) 或本机 Ollama Cloud:DEEPSEEK_BASE=http://127.0.0.1:11434/v1 "
            "DEEPSEEK_MODEL=deepseek-v4-pro:cloud DEEPSEEK_API_KEY=ollama\n"
            "  3) 实况名与默认 %s 不符则设 DEEPSEEK_MODEL" % DS_MODEL
        )
    base = DS_BASE
    if base.endswith("/v1"):
        url = base + "/chat/completions"
    elif "deepseek.com" in base:
        url = base.rstrip("/") + "/chat/completions"
    else:
        url = base + "/chat/completions"
    body = {
        "model": DS_MODEL,
        # v4-pro:cloud 即使 think=false 仍产 message.reasoning,计入 completion;
        # 2000 会被 reasoning 吃光 → content 空(实测 2026-08-05)。4500=推理税+正文。
        "max_tokens": 4500,
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


def build_glm_review_prompt(mode: str, ds_draft: str) -> str:
    """GLM = review/编译官(Lyra 拍板的十句任务)。"""
    if mode == "morning":
        must = (
            "晨报终稿主菜必须是 S&P 500 + Nasdaq 个股观察卡(1–3 只)。"
            "每只个股仍含 Patch 7 四段:①方向判断+置信度 ②关键行权价 "
            "③具体策略(行权价/到期/最大亏损) ④放弃条件。"
            "SPY/QQQ 只许出现在短「大盘环境」;禁止把 SPY/QQQ 写成③策略标的或可执行清单主菜。"
            "若 DS 误写成 SPY 卖 put/买 call 为主菜:改排为附录或删策略段,把个股卡抬成正文。"
            "工作站 :8620 的 GEX/gamma_flip/IVP/VRP 是真读数——保留并核对。"
            "无实盘报价处保留「无实盘报价 · 仅结构建议」;禁止补编 mid/ask。"
        )
    else:
        must = (
            "晚报终稿必须仍含四段:①要闻催化 ②赔率变化 ③明日日历 "
            "④明日关注。"
        )
    return f"""你是 Scout 流水线的 review / 编译官,不是首席决策官。

上游 DeepSeek 已写好一份{"晨会交易任务单" if mode == "morning" else "晚报复盘"}(中文 Markdown)。
DeepSeek 负责读隔夜采集与 workstation(:8620) GEX/特征真读数并给出分析作业;你负责审一遍、编成更清晰可读的最终稿。
{must}
可以改表述、补小标题、标出矛盾或缺数据;不得凭空改价位、编造 GEX/OI、偷换策略逻辑。
若 DS 已标注 synthetic-v1 / 数据缺失,必须保留该标注,不得洗成真盘结论。
禁止空话(「视情况而定」「谨慎操作」);不确定就写缺什么、为何无法确认。
输出只要最终 Markdown 正文;这是给 Lyra 看的参谋稿,不是自动下单指令。

—— DeepSeek 原稿 ——
{ds_draft[:9000]}
"""


def glm_review(mode: str, ds_draft: str) -> str:
    """经 8501 /v1/chat/completions 调 GLM 编译终稿。失败则响亮降级用 DS 原稿。"""
    prompt = build_glm_review_prompt(mode, ds_draft)
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


def emit_aether(
    date: str,
    mode: str,
    title: str,
    body: str,
    bp: str,
    ws=None,
    *,
    ds_draft: str = "",
    glm_final: str = "",
    ds_task_id=None,
    glm_task_id=None,
) -> None:
    payload = {
        "date": date,
        "mode": mode,
        "title": title,
        "body": body,  # 兼容旧 UI:终稿
        "glm_final": glm_final or body,
        "ds_draft": ds_draft or "",
        "via": "scout_v3_ds_glm",
        "brief_path": bp,
        "workstation": ws,
        "console_ds_task": ds_task_id,
        "console_glm_task": glm_task_id,
        "pipeline": "DS决策官→GLM review编译",
    }
    data = json.dumps(
        {"source": "aether", "kind": "aether_scout_brief", "payload": payload},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        GW + "/store/events",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            print(
                "[scout] aether OPTION emit",
                "ok" if 200 <= resp.status < 300 else resp.status,
            )
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print("[scout] aether emit 失败(响亮):", e)


def archive_console(title: str, ds_draft: str, glm_final: str, mode: str):
    """DS 原稿 → deepseek_lane;GLM 终稿 → glm_lane(deps DS)。返回 task ids。"""
    ds_id = glm_id = None
    if not CONSOLE_KEY:
        print("[scout] CONSOLE_KEY 未配置 → 跳过 console 存档")
        return None, None
    try:
        t1 = _http(
            CONSOLE + "/api/tasks",
            {
                "workspace": "trade",
                "title": title + " · DS原稿",
                "owner_node": "deepseek_lane",
                "risk_level": "read",
                "io_contract": "[DS 决策官作业,存档] " + ds_draft[:8000],
            },
            {"X-Console-Key": CONSOLE_KEY},
        )
        ds_id = t1.get("task_id")
        print("[scout] console DS#%s" % ds_id)
        t2 = _http(
            CONSOLE + "/api/tasks",
            {
                "workspace": "trade",
                "title": title + " · GLM终稿",
                "owner_node": "glm_lane",
                "risk_level": "read",
                "deps": [ds_id] if ds_id else [],
                "io_contract": (
                    "[GLM review 编译终稿,存档] mode=%s\n" % mode + glm_final[:8000]
                ),
            },
            {"X-Console-Key": CONSOLE_KEY},
        )
        glm_id = t2.get("task_id")
        print("[scout] console GLM#%s" % glm_id)
    except Exception as e:
        print("[scout] console 存档失败(%s)→ 仅本地落盘" % e)
    return ds_id, glm_id


def write_briefs(title: str, glm_final: str, ds_draft: str, date: str, mode: str) -> str:
    """终稿=GLM;旁挂 DS 原稿供一周 A/B。"""
    bp = os.path.join(OUT, "briefs", "%s-%s.md" % (date, mode))
    os.makedirs(os.path.dirname(bp), exist_ok=True)
    text = (
        "# %s\n\n"
        "## GLM 终稿(review/编译)\n\n%s\n\n"
        "---\n\n"
        "## DS 原稿(A/B 对照 · 勿当终稿)\n\n%s\n"
        % (title, glm_final.strip(), ds_draft.strip())
    )
    with open(bp, "w", encoding="utf-8") as f:
        f.write(text)
    if mode == "morning":
        alt = os.path.join(OUT, "briefs", "%s_morning_task.md" % date)
        with open(alt, "w", encoding="utf-8") as f:
            f.write(text)
        # 纯终稿另存一份,方便你扫一眼
        final_only = os.path.join(OUT, "briefs", "%s-morning-final.md" % date)
        with open(final_only, "w", encoding="utf-8") as f:
            f.write("# %s\n\n%s\n" % (title, glm_final.strip()))
    print("[scout] 落盘:", bp)
    return bp


def run_pipeline(mode: str, payload: dict, today: str, yday, ws=None):
    if mode == "morning":
        title = "Scout 晨会交易任务单 · " + today
        print("[scout] DS 决策官…")
        ds_draft = ds_call(build_trading_prompt(payload, ws, yday))
    else:
        title = "Scout 晚报复盘 · " + today
        print("[scout] DS 决策官…")
        ds_draft = ds_call(build_evening_prompt(payload, yday))
    print("[scout] DS 作业 %d 字符 → GLM review…" % len(ds_draft))
    glm_final = glm_review(mode, ds_draft)
    ds_id, glm_id = archive_console(title, ds_draft, glm_final, mode)
    bp = write_briefs(title, glm_final, ds_draft, today, mode)
    # OPTION:终稿 + 原稿(可折叠对照,审 GLM 这步要不要)
    emit_aether(
        today,
        mode,
        title,
        glm_final,
        bp,
        ws=ws,
        ds_draft=ds_draft,
        glm_final=glm_final,
        ds_task_id=ds_id,
        glm_task_id=glm_id,
    )
    return bp


def main():
    ap = argparse.ArgumentParser(description="Scout Agent v3(DS→GLM)")
    ap.add_argument("--mode", choices=["evening", "morning"], default="evening")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-fetch", action="store_true")
    a = ap.parse_args()
    today = datetime.date.today().isoformat()
    os.makedirs(os.path.join(OUT, "raw"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "briefs"), exist_ok=True)

    _, payload = load_raw(today, skip_fetch=a.skip_fetch)

    if a.dry_run:
        print("[scout] --dry-run 止步于采集")
        return

    yday = yesterday_raw(today)
    ws = fetch_workstation_state() if a.mode == "morning" else None
    run_pipeline(a.mode, payload, today, yday, ws=ws)


if __name__ == "__main__":
    main()

