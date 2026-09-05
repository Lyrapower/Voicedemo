#!/usr/bin/env python3
"""scout_agent.py —— Scout Agent v3(作战单版 · Lyra 拍板)

定位:给 Lyra 递作战数字的参谋,不是写报纸的。

晨报 06:45 PST → briefs/日期-morning.md + 日期_morning_task.md
  ① OI 异动(Polygon) ② 板块轮动(FMP) ③ Call 候选卡(Polygon+8620)
  ④ workstation 读数(8620) ⑤ 赔率+隔夜要闻(Polymarket+DS 配菜)
  ①②③④ 全确定性;LLM 碰不到价位。

晚报 21:00 PST → briefs/日期-evening.md
  OI 复盘骨架 + 日历 + DS 宏观配菜;console 任务链仍可归档 work_log。

卡点:POLYGON_API_KEY + FMP_API_KEY。
"""
from __future__ import annotations
import argparse, datetime, json, os, re, sys, time, urllib.error, urllib.request
from pathlib import Path

import fetchers
from v3_modules import build_evening_recap, build_morning_battle
from v3_modules.odds_news import ds_news_digest

_HERE = Path(__file__).resolve().parent
_DEMO = Path(os.path.expanduser("~/Projects/demo"))


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
GW = os.getenv("GATEWAY_URL", "http://127.0.0.1:8501")
GLM_MODEL = os.getenv("GLM_MODEL", "glm-5.2:cloud")
CONSOLE = os.getenv("CONSOLE_URL", "http://localhost:8610")
CONSOLE_KEY = os.getenv("CONSOLE_KEY", "").strip()
OWS = os.getenv("OWS_URL", "http://localhost:8620")
OUT = os.getenv("SCOUT_OUT", str(_HERE))
SIGNAL_PATTERNS = os.getenv(
    "SIGNAL_PATTERNS",
    str(_DEMO / "config" / "signal_patterns.json"),
)


def _http(url, body=None, headers=None, timeout=90):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method="POST" if data else "GET",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


_SIG = None


def _sig_re():
    global _SIG
    if _SIG is None:
        try:
            with open(SIGNAL_PATTERNS, encoding="utf-8") as f:
                pats = json.load(f).get("patterns", [])
            _SIG = re.compile("|".join(pats)) if pats else False
        except Exception:
            _SIG = False
    return _SIG


def scrub(text: str):
    """晚报 work_log 路径过闸;晨会作战单数字不过闸(确定性模块)。"""
    rx = _sig_re()
    if rx is False:
        return text, "signal_check=unavailable"
    kept, hits = [], 0
    for ln in text.splitlines():
        if rx.search(ln):
            kept.append("[信号拦截]")
            hits += 1
        else:
            kept.append(ln)
    return "\n".join(kept), "signal_check=on hits=%d" % hits


def resolve_raw_path(today: str, *, skip_fetch: bool) -> tuple[str, dict]:
    raw_dir = os.path.join(OUT, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    today_path = os.path.join(raw_dir, today + ".json")
    if skip_fetch:
        if os.path.exists(today_path):
            with open(today_path, encoding="utf-8") as f:
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
        print("[scout] --skip-fetch:复用 %s" % path)
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


def emit_scout_brief(payload: dict) -> bool:
    body = json.dumps(
        {"source": "aether", "kind": "aether_scout_brief", "payload": payload},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        GW.rstrip("/") + "/store/events",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            ok = 200 <= resp.status < 300
            print("[scout] aether OPTION emit %s" % ("ok" if ok else resp.status))
            return ok
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print("[scout] aether emit 失败:", e)
        return False


def write_morning_files(date: str, md: str) -> str:
    primary = os.path.join(OUT, "briefs", "%s-morning.md" % date)
    also = os.path.join(OUT, "briefs", "%s_morning_task.md" % date)
    for p in (primary, also):
        with open(p, "w", encoding="utf-8") as f:
            f.write(md)
    print("[scout] 作战单落盘:", primary)
    return primary


def write_evening_file(date: str, md: str) -> str:
    path = os.path.join(OUT, "briefs", "%s-evening.md" % date)
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    print("[scout] 晚报落盘:", path)
    return path


def _console_get(path, timeout=30):
    return _http(CONSOLE + path, None, {"X-Console-Key": CONSOLE_KEY}, timeout=timeout)


def wait_console_task(task_id, *, timeout_s=600, poll_s=5):
    if not task_id:
        return {}
    deadline = time.time() + timeout_s
    last = {}
    while time.time() < deadline:
        last = _console_get("/api/tasks/%s" % task_id, timeout=30) or {}
        if last.get("status") in ("done", "failed", "rejected", "error"):
            return last
        time.sleep(poll_s)
    return last


def task_stdout(detail: dict) -> str:
    logs = detail.get("logs") or []
    outs = [x.get("line") or "" for x in logs if x.get("kind") == "stdout"]
    return (outs[-1] if outs else "").strip()


def fetch_work_log_snip(node: str, task_id, *, limit=80, max_chars=400) -> str:
    if not task_id:
        return ""
    try:
        rows = _http(
            "%s/store/conversations/%s?limit=%d" % (GW.rstrip("/"), node, limit),
            None,
            timeout=20,
        )
    except Exception:
        return ""
    if isinstance(rows, dict):
        rows = rows.get("messages") or rows.get("items") or []
    needle = "task_id=%s" % task_id
    for m in reversed(rows or []):
        c = str((m or {}).get("content") or "")
        if "[工作日志]" in c and needle in c:
            return c[:max_chars]
    return ""


def run_morning(today: str, payload: dict, *, run_ds: bool = True) -> str:
    print("[scout] v3 晨报作战单 · 确定性模块①②③④ + DS配菜⑤")
    built = build_morning_battle(today, payload, run_ds=run_ds)
    md = built["markdown"]
    bp = write_morning_files(today, md)
    pack = built["pack"]
    ws_items = (pack.get("ws") or {}).get("items") or {}
    emit_scout_brief({
        "date": today,
        "mode": "morning",
        "title": "Scout 作战单 · %s" % today,
        "body": md,
        "via": "scout_v3",
        "signal": "deterministic_modules",
        "brief_path": bp,
        "workstation": {
            k: ws_items.get(k)
            for k in (
                "date", "underlying", "spot", "net_gex", "gamma_flip",
                "ivp", "ivr", "vrp20", "source",
            )
        },
        "blocks": {
            "oi_ok": bool((pack.get("oi") or {}).get("ok")),
            "sectors_ok": bool((pack.get("sectors") or {}).get("ok")),
            "calls_n": len((pack.get("calls") or {}).get("cards") or []),
            "ws_ok": bool((pack.get("ws") or {}).get("ok")),
            "news_ok": bool((pack.get("news") or {}).get("ok")),
            "polygon": bool(os.getenv("POLYGON_API_KEY", "").strip()),
            "fmp": bool(os.getenv("FMP_API_KEY", "").strip()),
        },
    })
    return bp


def run_evening(today: str, payload: dict, *, no_wait: bool = False) -> str:
    print("[scout] v3 晚报 · DS 配菜 + console 归档(可选)")
    news = ds_news_digest(json.dumps(payload, ensure_ascii=False))
    ds_lines = news.get("lines") or []
    md = build_evening_recap(today, payload, ds_lines=ds_lines)
    # 可选:把 DS 原文 scrub 后附在晚报尾(情报归档)
    if news.get("raw"):
        scrubbed, sig = scrub(news["raw"])
        md += "\n## DS 原文(过闸)\n%s\n[%s]\n" % (scrubbed, sig)
    bp = write_evening_file(today, md)

    ds_id = glm_id = None
    ds_st = glm_st = ""
    try:
        if not CONSOLE_KEY:
            raise RuntimeError("CONSOLE_KEY 未配置")
        # console 只存档摘要,不把作战价位丢进 lane
        digest = "\n".join(ds_lines) if ds_lines else md[:4000]
        t1 = _http(
            CONSOLE + "/api/tasks",
            {
                "workspace": "trade",
                "title": "晚报·DS 消化 %s" % today,
                "owner_node": "deepseek_lane",
                "risk_level": "read",
                "io_contract": "[scout_v3 evening archive] " + digest[:6000],
            },
            {"X-Console-Key": CONSOLE_KEY},
        )
        t2 = _http(
            CONSOLE + "/api/tasks",
            {
                "workspace": "trade",
                "title": "晚报·编译 %s" % today,
                "owner_node": "glm_lane",
                "risk_level": "read",
                "deps": [t1.get("task_id")] if t1.get("task_id") else [],
                "io_contract": (
                    "将下列晚报骨架整理为可读复盘(禁编造价位/方向指令):\n" + md[:7000]
                ),
            },
            {"X-Console-Key": CONSOLE_KEY},
        )
        ds_id, glm_id = t1.get("task_id"), t2.get("task_id")
        print("[scout] console DS#%s → GLM#%s" % (ds_id, glm_id))
        if not no_wait:
            ds_detail = wait_console_task(ds_id, timeout_s=180)
            glm_detail = wait_console_task(glm_id, timeout_s=600)
            ds_st = ds_detail.get("status") or ""
            glm_st = glm_detail.get("status") or ""
            gout = task_stdout(glm_detail)
            if gout and len(gout) > 80:
                # 保留确定性晚报为主;GLM 可读性附录
                with open(bp, "a", encoding="utf-8") as f:
                    f.write("\n## GLM 可读性附录\n%s\n" % scrub(gout)[0])
    except Exception as e:
        print("[scout] console 归档跳过(%s)——晚报文件已落盘" % e)

    emit_scout_brief({
        "date": today,
        "mode": "evening",
        "title": "Scout 晚报 · %s" % today,
        "body": Path(bp).read_text(encoding="utf-8"),
        "via": "scout_v3",
        "brief_path": bp,
        "console_ds_task": ds_id,
        "console_glm_task": glm_id,
        "console_ds_status": ds_st,
        "console_glm_status": glm_st,
        "work_log_ds": fetch_work_log_snip("cloud-deepseek", ds_id),
        "work_log_glm": fetch_work_log_snip("cloud-glm52", glm_id),
    })
    return bp


def emit_from_disk(date: str, mode: str) -> int:
    if mode == "morning":
        candidates = [
            os.path.join(OUT, "briefs", "%s-morning.md" % date),
            os.path.join(OUT, "briefs", "%s_morning_task.md" % date),
        ]
    else:
        candidates = [os.path.join(OUT, "briefs", "%s-evening.md" % date)]
    bp = next((p for p in candidates if os.path.isfile(p)), None)
    if not bp:
        print("[scout] --emit-only 无文件", candidates)
        return 2
    body = Path(bp).read_text(encoding="utf-8")
    emit_scout_brief({
        "date": date,
        "mode": mode,
        "title": "Scout %s · %s" % ("作战单" if mode == "morning" else "晚报", date),
        "body": body,
        "via": "emit-only",
        "brief_path": bp,
    })
    return 0


def main():
    ap = argparse.ArgumentParser(description="Scout Agent v3 · 作战单")
    ap.add_argument("--mode", choices=["evening", "morning"], default="evening")
    ap.add_argument("--dry-run", action="store_true", help="只采集或只拼卡(晨报可 --no-ds)")
    ap.add_argument("--skip-fetch", action="store_true")
    ap.add_argument("--no-ds", action="store_true", help="晨报跳过 DS 配菜(测①-④)")
    ap.add_argument("--emit-only", action="store_true")
    ap.add_argument("--date", default="")
    ap.add_argument("--no-wait-console", action="store_true")
    a = ap.parse_args()
    today = (a.date or datetime.date.today().isoformat()).strip()
    os.makedirs(os.path.join(OUT, "briefs"), exist_ok=True)

    if a.emit_only:
        raise SystemExit(emit_from_disk(today, a.mode))

    if a.dry_run and a.mode == "morning":
        _, payload = resolve_raw_path(today, skip_fetch=a.skip_fetch or True)
        built = build_morning_battle(today, payload, run_ds=False)
        bp = write_morning_files(today, built["markdown"])
        print("[scout] --dry-run 晨报结构已写(无 DS):", bp)
        print(built["markdown"][:1600])
        return

    if a.dry_run:
        resolve_raw_path(today, skip_fetch=a.skip_fetch)
        print("[scout] --dry-run 止步于采集")
        return

    _, payload = resolve_raw_path(today, skip_fetch=a.skip_fetch)
    if a.mode == "morning":
        run_morning(today, payload, run_ds=not a.no_ds)
    else:
        run_evening(today, payload, no_wait=a.no_wait_console)


if __name__ == "__main__":
    main()
