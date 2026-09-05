#!/usr/bin/env python3
"""scout_agent.py —— Scout Agent v3(DS 决策官 → GLM 5.2 review/编译)

流水线:
  fetchers → raw → DeepSeek 决策官作业 → GLM review/编译终稿
  → briefs/ 落盘 + console 双 lane + aether_scout_brief(OPTION)

DS = 参谋作业(Ollama Cloud · deepseek-v4-pro:cloud)
GLM = review/编译官(8501 · glm-5.2:cloud);失败则响亮降级用 DS 原稿
晨报强制:个股观察卡 + 禁编权利金/mid/ask。
"""
from __future__ import annotations
import argparse, datetime, json, os, sys, urllib.error, urllib.request
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
GLM_MODEL = os.getenv("GLM_MODEL", "glm-5.2:cloud")
CONSOLE = os.getenv("CONSOLE_URL", "http://localhost:8610").rstrip("/")
CONSOLE_KEY = os.getenv("CONSOLE_KEY", "").strip()
OWS = os.getenv("OWS_URL", "http://localhost:8620").rstrip("/")
OUT = os.getenv("SCOUT_OUT", str(_HERE))

# 晨报共用硬约束(DS + GLM)
MORNING_HARD = """
硬约束(违反即不合格):
- 主菜必须是 S&P 500 / Nasdaq 池内「个股观察卡」1–3 只;每卡四段:
  ①方向判断+置信度 ②关键价位/行权价结构 ③具体策略(结构/行权价/到期/最大亏损口径)
  ④放弃条件
- 每卡候选必须锚定隔夜采集具体条目(EDGAR/FDA/赔率/指数等);无证据 → 写
  「今日池内无事件驱动候选」,禁止凭训练记忆点名
- SPY/QQQ 只许出现在短「大盘环境」;禁止把 SPY/QQQ 写成策略标的或清单主菜
- **禁编权利金**:禁止编造 mid/ask/bid、单腿美元权利金、总成本 $X、$600 这类假精确报价;
  无实盘报价时必须写「无实盘报价 · 仅结构建议」;最大亏损只许写结构口径
  (如「净权利金支出」「行权价−权利金(若被指派)」),不得填假数字
- 无 :8620 实弹 / 仅 synthetic-v1 时:不得把合成 GEX 当真盘;标明缺失即可
- 禁止「视情况而定」「谨慎操作」等空话
""".strip()


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


def build_trading_prompt(raw, ws, yday):
    return f"""你是交易台的首席决策官。开盘在即,基于隔夜数据给出分析作业
(给交易员看的参谋稿,不是自动下单)。
观察宇宙 = S&P 500 与 Nasdaq 成分池(不是 SPY/QQQ 两只 ETF)。

{MORNING_HARD}

输出结构(Markdown):
## A. 大盘环境
- SP500 / Nasdaq 偏向 + 置信度 + 逻辑(引用 indices/收益率/VIX/赔率;有 :8620 实弹才引用 GEX)
- SPY/QQQ 仅环境参考,一两句即可

## B. 个股观察卡(主菜,1–3 只)
### 卡 N · TICKER
①方向+置信度 ②关键价位/行权价结构 ③策略(结构/行权价/到期/最大亏损口径;无报价则「无实盘报价 · 仅结构建议」)
④放弃条件
每卡末尾一行出处:锚定的隔夜采集条目。

## C. 可执行清单(表)
标的 | 结构 | 入场条件 | 放弃条件
(无报价、非指令)

隔夜采集:{json.dumps(raw, ensure_ascii=False)[:6000]}
工作站读数(GEX/特征):{json.dumps(ws, ensure_ascii=False) if ws else "工作站无可用实弹数据(不可达或仅合成数据),基于隔夜数据判断——勿编造 GEX"}
昨日采集(对比用):{json.dumps(yday, ensure_ascii=False)[:2000] if yday else "无"}
用中文。"""


def build_evening_prompt(raw, yday):
    return f"""你是交易台参谋。写今日收盘复盘 + 明日弹药,给交易员看:
1. 今日要闻与并购/FDA/事件催化(带出处)
2. 隔夜→今日的赔率变化(Polymarket)
3. 明日日历(FDA/到期/财报/事件)
4. 明日值得盯的方向与关键位(分析,非指令)
禁止编造未出现在采集中的价格/权利金。
今日采集:{json.dumps(raw, ensure_ascii=False)[:6000]}
昨日对比:{json.dumps(yday, ensure_ascii=False)[:1500] if yday else "无"}
用中文,给数字给出处,不写废话。"""


def ds_call(prompt):
    if not DS_KEY:
        raise SystemExit(
            "[scout] DEEPSEEK_API_KEY 未配置。\n"
            "  默认本机 Ollama Cloud:\n"
            "    DEEPSEEK_BASE=http://127.0.0.1:11434/v1\n"
            "    DEEPSEEK_MODEL=deepseek-v4-pro:cloud\n"
            "    DEEPSEEK_API_KEY=ollama\n"
            "  当前 BASE=%s MODEL=%s" % (DS_BASE, DS_MODEL)
        )
    if DS_BASE.endswith("/v1"):
        url = DS_BASE + "/chat/completions"
    elif "deepseek.com" in DS_BASE:
        url = DS_BASE.rstrip("/") + "/chat/completions"
    else:
        url = DS_BASE + "/chat/completions"
    body = {
        "model": DS_MODEL,
        # 长 prompt + v4-pro 仍产 reasoning 时,4500 不够 → content 空(finish=length)。
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


def build_glm_review_prompt(mode: str, ds_draft: str) -> str:
    if mode == "morning":
        must = (
            MORNING_HARD
            + "\n"
            + "若 DS 误写成 SPY/QQQ 策略为主菜:改排附录或删除,把个股卡抬成正文。\n"
            "若 DS 编了权利金/$数字:删掉假报价,改为「无实盘报价 · 仅结构建议」。\n"
            "若 DS 已标 synthetic/数据缺失:必须保留,不得洗成真盘。"
        )
    else:
        must = "晚报终稿仍含四段:①要闻催化 ②赔率变化 ③明日日历 ④明日关注。禁止补编采集中没有的数字。"
    return f"""你是 Scout 流水线的 review / 编译官(GLM 5.2),不是首席决策官。

上游 DeepSeek 已写好一份{"晨会交易任务单" if mode == "morning" else "晚报复盘"}。
你审一遍、编成更清晰可读的最终稿。
{must}
可以改表述、补小标题、标出矛盾或缺数据;不得凭空改价位、编造 GEX/OI、偷换策略逻辑、补编权利金。
输出只要最终 Markdown 正文;给 Lyra 看的参谋稿,不是自动下单指令。

—— DeepSeek 原稿 ——
{ds_draft[:9000]}
"""


def glm_review(mode: str, ds_draft: str) -> str:
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
        "body": body,
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
        final_only = os.path.join(OUT, "briefs", "%s-morning-final.md" % date)
        with open(final_only, "w", encoding="utf-8") as f:
            f.write("# %s\n\n%s\n" % (title, glm_final.strip()))
    print("[scout] 落盘:", bp)
    return bp


def run_pipeline(mode: str, payload: dict, today: str, yday, ws=None):
    if mode == "morning":
        title = "Scout 晨会交易任务单 · " + today
    else:
        title = "Scout 晚报复盘 · " + today
    print("[scout] DS 决策官…")
    if mode == "morning":
        ds_draft = ds_call(build_trading_prompt(payload, ws, yday))
    else:
        ds_draft = ds_call(build_evening_prompt(payload, yday))
    print("[scout] DS 作业 %d 字符 → GLM review…" % len(ds_draft))
    glm_final = glm_review(mode, ds_draft)
    ds_id, glm_id = archive_console(title, ds_draft, glm_final, mode)
    bp = write_briefs(title, glm_final, ds_draft, today, mode)
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

    if a.dry_run:
        print("[scout] --dry-run 止步于采集")
        return

    yday = yesterday_raw(today)
    ws = fetch_workstation_state() if a.mode == "morning" else None
    run_pipeline(a.mode, payload, today, yday, ws=ws)


if __name__ == "__main__":
    main()
