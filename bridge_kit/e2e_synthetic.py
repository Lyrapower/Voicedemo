"""端到端(沙箱内,假 8630/假 Grid):Grid 文本 → 抽块 → 编译 → 假 8630 派 mission → 收据 → 回链 → 输入流 → 自证。
真机上把 fake_8630 换成 POST /api/missions,其余不变。"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge_kit import h1_job_block as h1, grid_inbound as gi, tool_hints as th

GRID_TEXT = """收到。这件事可以让 harness 去做。
```job
type: MISSION
action.goal: fetch https://api.github.com/zen and report status
bounds.gate: read_only
bounds.budget: 3 hops / 5 min / $0
bounds.stop: first ok receipt
resources.worker: deep
resources.tools: web.fetch
```
"""

def fake_8630_create_mission(compiled):
    # 真机:create_mission 由 8630 分配 mid 并写 job.lane(来自 mission.lane);seed_hash 只做相关性不授权
    return "M-" + compiled["seed_hash"][:12]

def fake_worker_run(compiled):
    url = "https://api.github.com/zen"
    assert th.check_web_fetch_url(url) is None
    body = "Keep it logically awesome."
    r = {"jid": "J-e2e000000001", "tool": "web.fetch", "status": "ok", "chars": len(body),
         "grade": "unverified", "lane": th.lane_for_job({"jid": "J-e2e000000001", "worker": compiled["resources"]["worker"], "lane": "deep"})}
    return th.annotate_semantic(r, body)

def main():
    d = tempfile.mkdtemp()
    stream = os.path.join(d, "grid_input_stream.txt")
    blocks = h1.extract_job_blocks(GRID_TEXT); assert len(blocks) == 1
    compiled = h1.compile_job(h1.parse_job_block(blocks[0]), origin="synthetic_xu", block_text=blocks[0])
    mid = fake_8630_create_mission(compiled)
    receipt = h1.attach_lineage(fake_worker_run(compiled), compiled, mission_ref=mid)
    w = gi.InboundWriter(stream)
    assert w.write(receipt) == "written"
    assert w.write(receipt) == "duplicate"
    row = open(stream, encoding="utf-8").read().strip()
    assert h1.verify_roundtrip(compiled, row), row
    assert "semantic" not in row  # 输入流只放收据原行的固定字段
    print(json.dumps({"mission_ref": mid, "seed_hash": compiled["seed_hash"][:16], "row": row}, ensure_ascii=False))
    print("E2E_SYNTHETIC_OK")

if __name__ == "__main__":
    main()
