#!/usr/bin/env python3
"""8501/factory/task 联调一轮:真 propose_factor(真 LLM),temp db,不碰生产 platform.db。
验证:end-to-end 8501 LLM propose 路径通,返回 code+hypothesis+route+trace_id,draft 落表。"""
import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "alpha-platform", "backend"))
os.environ["PLATFORM_DB_DIRECT_WRITE"] = "1"

tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False, mode="w")
tmp.close()
os.environ["PLATFORM_DB"] = tmp.name
os.environ.setdefault("WATCHLIST", "AAPL,MSFT,NVDA,TSLA")

print("=== 8501 联调:propose_factor(真 LLM) ===")
print("PLATFORM_DB=%s" % tmp.name)
print("WATCHLIST=%s" % os.environ["WATCHLIST"])

try:
    import factory_pipeline
    print("[step1] propose_factor(idea='动量:过去5日收益截面排名', test=True) ...")
    res = factory_pipeline.propose_factor("动量:过去5日收益截面排名,做多 top 20%", test=True, budget_hint="std")
    print("[step1 OK] draft_id=%s status=%s route=%s trace_id=%s" % (
        res.get("draft_id"), res.get("status"), res.get("route"), res.get("trace_id")))
    print("  hypothesis: %s" % (res.get("hypothesis") or "")[:200])
    code = (res.get("code") or "")
    if not code:
        # propose_factor 不返回 code(只返回 draft_id);从 db 读
        import db
        c = db.conn_factory()
        row = c.execute("SELECT code, hypothesis FROM factor_drafts WHERE id=?", (res["draft_id"],)).fetchone()
        c.close()
        code, hyp = row[0] or "", row[1] or ""
        print("  hypothesis(db): %s" % hyp[:200])
    print("  code (前 400 字):\n%s" % (code[:400]))
    print("  code 长度: %d" % len(code))
    has_factor = "def factor" in code
    print("  含 def factor: %s" % has_factor)
    print("[联调结论] %s" % ("PASS — 真 8501 LLM propose 路径通,draft 落表,code 含 factor()" if has_factor else "FAIL — code 不含 factor()"))
except Exception as exc:
    print("[联调异常] %s: %s" % (type(exc).__name__, str(exc)[:400]))
    traceback.print_exc()
finally:
    try:
        os.unlink(tmp.name)
    except OSError:
        pass
