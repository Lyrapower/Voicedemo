#!/usr/bin/env python3
"""bars 灌注 + 真 review 闭环:FMP 日线 → temp db bars → 真 propose(8501)→ 真 sandbox review → trajectory 真指标。

不碰生产 platform.db(temp db);不读/不打印 .env 值(只 setdefault 进进程 env);不改 gateway(只客户端调)。
验证:真 bars 进 db → 真 LLM 产因子 → 真 sandbox 算真 IC/IR → trajectory 落表带真指标。
"""
import os
import sys
import tempfile
import traceback

BACKEND = os.path.join(os.path.dirname(__file__), "..", "alpha-platform", "backend")
sys.path.insert(0, BACKEND)
os.environ["PLATFORM_DB_DIRECT_WRITE"] = "1"


def _load_env_quiet(path):
    """加载 .env 进 os.environ(setdefault,不覆盖,不打印值)。"""
    if not os.path.exists(path):
        return 0
    n = 0
    for line in open(path, encoding="utf-8"):
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k.upper() in ("FMP_API_KEY", "ALPACA_API_KEY", "ALPACA_SECRET_KEY", "FMP_BASE"):
            os.environ.setdefault(k, v)
            n += 1
    return n


# 加载 .env(优先 alpha-platform,再 grid-scout,再 root)
for p in [os.path.join(BACKEND, ".env"),
           os.path.join(os.path.dirname(__file__), "..", "grid-scout", ".env"),
           os.path.join(os.path.dirname(__file__), "..", ".env")]:
    _load_env_quiet(p)

tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False, mode="w")
tmp.close()
os.environ["PLATFORM_DB"] = tmp.name
SYMS = ["AAPL", "MSFT", "NVDA", "AMZN", "TSLA", "PLTR"]
os.environ.setdefault("WATCHLIST", ",".join(SYMS))

print("=== bars 灌注 + 真 review 闭环 ===")
print("PLATFORM_DB=%s" % tmp.name)
print("WATCHLIST=%s" % os.environ["WATCHLIST"])
print("FMP_API_KEY set: %s" % ("yes" if os.getenv("FMP_API_KEY") else "NO — FMP 不可用"))

try:
    import db
    import factor_truth
    from worker import _store_bars

    # ---- step1: FMP 日线灌注 ----
    print("\n[step1] FMP 日线灌注 ...")
    c = db.conn()
    total = 0
    per_sym = {}
    for sym in SYMS:
        bars = factor_truth.fetch_fmp_daily_bars(sym, limit=120)
        n = _store_bars(c, sym, bars)
        per_sym[sym] = n
        total += n
        print("  %s: %d bars" % (sym, n))
    c.commit()
    c.close()
    print("[step1] 共 %d bars,per_sym=%s" % (total, per_sym))
    if total < 30:
        print("[step1 FAIL] bars 不足 30,沙箱会拒;退出")
        sys.exit(2)

    # ---- step2: 真 propose(8501 LLM)----
    import factory_pipeline
    print("\n[step2] propose_factor(真 8501 LLM) ...")
    res = factory_pipeline.propose_factor("动量:过去5日收益截面排名,做多 top 20%", test=True, budget_hint="std")
    draft_id = res["draft_id"]
    print("[step2 OK] draft_id=%s route=%s trace_id=%s" % (draft_id, res.get("route"), res.get("trace_id")))

    # ---- step3: 真 sandbox review ----
    print("\n[step3] start_review(真 sandbox) ...")
    job_id = factory_pipeline.start_review(draft_id)
    import time
    deadline = time.time() + 120
    status = "running"
    while time.time() < deadline:
        jc = db.conn_jobs()
        try:
            row = jc.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        finally:
            jc.close()
        if row and row[0] == "done":
            status = "done"
            break
        time.sleep(0.5)
    print("[step3] review status=%s" % status)

    # ---- step4: 读 trajectory + 真 metrics ----
    import factor_evolution
    c = db.conn_factory()
    factor_evolution.ensure_trajectory_schema(c)
    # review 结果
    rev = c.execute("SELECT status, metrics, error FROM factor_reviews WHERE draft_id=? ORDER BY id DESC LIMIT 1", (draft_id,)).fetchone()
    traj = c.execute("SELECT id, outcome, reward, ic, ir, direction FROM factor_trajectories WHERE draft_id=? ORDER BY id DESC LIMIT 1", (draft_id,)).fetchone()
    c.close()
    print("\n[step4] review: status=%s" % (rev[0] if rev else "none"))
    if rev and rev[1]:
        import json
        m = json.loads(rev[1])
        print("  metrics: ic=%s ir=%s n_obs=%s" % (m.get("ic"), m.get("ir"), m.get("n_obs")))
    if rev and rev[2]:
        print("  error: %s" % (rev[2][:200]))
    if traj:
        print("[step4] trajectory: id=%s outcome=%s reward=%s ic=%s ir=%s direction=%s" % traj)
        print("\n[闭环结论] %s" % (
            "PASS — 真 bars→真 LLM→真 sandbox→真 IC/IR→trajectory 落表" if (traj and traj[3] is not None) else
            "PARTIAL — review 跑了但无真指标(可能 sandbox 拒或 bars 不足)"))
    else:
        print("[step4] trajectory 未落表")
        print("\n[闭环结论] PARTIAL — trajectory 未落")
except Exception as exc:
    print("[异常] %s: %s" % (type(exc).__name__, str(exc)[:400]))
    traceback.print_exc()
finally:
    try:
        os.unlink(tmp.name)
    except OSError:
        pass
