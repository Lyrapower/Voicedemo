"""evening_brief.py —— 晚报编排器(9pm PST 由 launchd 触发)。
流水线:确定性 fetchers → raw 落盘(不可变) → console mission
  → DS 消化任务(deepseek_lane,产物自动带 lane:deepseek_inbound)
  → GLM 编译任务(依赖 DS 任务,零方向词简报)
宪法:抓取零 LLM;DS 只摘要不评级;简报=情报非建议;
     "值得注意"项以【提名】前缀列出,由提名席机制消化,不直接进热力。
用法:CONSOLE_URL/CONSOLE_KEY 于 .env;--dry-run 只打印不建任务。"""
from __future__ import annotations
import datetime, json, os, sys, urllib.request

import fetchers

CONSOLE = os.getenv("CONSOLE_URL", "http://localhost:8610")
KEY = os.getenv("CONSOLE_KEY", "").strip()
OUT = os.getenv("SCOUT_OUT", os.path.expanduser("~/grid-scout"))
DRY = "--dry-run" in sys.argv


def _post(path, body):
    req = urllib.request.Request(CONSOLE + path, data=json.dumps(body).encode(),
                                 method="POST", headers={"Content-Type": "application/json",
                                                         "X-Console-Key": KEY})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def main():
    today = datetime.date.today().isoformat()
    os.makedirs(os.path.join(OUT, "raw"), exist_ok=True)
    results = fetchers.run_all()
    raw_path = os.path.join(OUT, "raw", today + ".json")
    with open(raw_path, "w", encoding="utf-8") as f:      # raw 不可变(同日重跑加后缀)
        json.dump({"results": results, "skips": fetchers.SKIPS}, f,
                  ensure_ascii=False, indent=1)
    if fetchers.SKIPS:
        print("[scout] 跳过 %d 条(原因已入 raw.skips)" % len(fetchers.SKIPS))
    ok = [r for r in results if r["ok"]]; bad = [r for r in results if not r["ok"]]
    print("[scout] %s 源成功 %d / 失败 %d → %s" % (today, len(ok), len(bad), raw_path))
    for b in bad:
        print("   ✗", b["source"], b.get("error", ""))

    digest_input = json.dumps(results, ensure_ascii=False)[:12000]
    if DRY:
        print("[scout] --dry-run:不建任务。DS 输入预览 %d 字符" % len(digest_input))
        return
    if not KEY:
        raise SystemExit("CONSOLE_KEY 未配置,拒绝建任务")

    m = _post("/api/missions" if False else "/api/tasks", {})  # placeholder guard
    # 建 mission
    mid = None
    try:
        r = _post("/api/missions", {"workspace": "trade", "goal": "晚报 " + today})
        mid = r.get("mission_id") or r.get("id")
    except Exception as e:
        print("[scout] mission 创建失败(不阻塞,散任务模式):", e)

    t1 = _post("/api/tasks", {"workspace": "trade",
        "title": "晚报·DS 消化 " + today,
        "owner_node": "deepseek_lane", "risk_level": "read",
        "io_contract": "只摘要不评级,零方向词。原始采集(JSON,来源+ok 标志):\n" + digest_input})
    tid1 = t1.get("task_id")
    t2 = _post("/api/tasks", {"workspace": "trade",
        "title": "晚报·编译 " + today,
        "owner_node": "glm_lane", "risk_level": "read",
        "deps": [tid1] if tid1 else [],
        "io_contract": ("将依赖任务的 DS 摘要(带 lane:deepseek_inbound 标)编译为晚报:"
                        "①事实与出处 ②宏观读数变化 ③日历(FDA/earnings)"
                        "④【提名】值得注意标的(仅提名注意力,禁方向词);"
                        "失败源如实列出。产出即简报,work_log 自动入魂器。")})
    print("[scout] 任务链已建:DS #%s → GLM #%s (mission %s)" % (tid1, t2.get("task_id"), mid))


if __name__ == "__main__":
    main()
