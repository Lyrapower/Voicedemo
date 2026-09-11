"""BRIDGE fixtures D2–D5 / D8 / D9. Isolated dest. No production chat writes."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from harness.db import Store
from harness.memory_bridge import (
    MemoryBridge, SELFTEST_NODE, SHARED_NODE, snapshot_forbidden, backfill,
    project_work_card, signal_blocked,
)


def run() -> dict:
    store = Store(str(Path(__file__).resolve().parents[1] / "state" / "harness.db"))
    out: dict = {"d2": "red", "d3": "red", "d4": "red", "d5": "red", "d8": "red", "d9": "red"}
    before = snapshot_forbidden()
    out["d5_before"] = before

    # D3 SIGNAL_RE
    fake = {
        "receipt_id": f"signal-{uuid.uuid4().hex[:8]}",
        "mid": "M-signal",
        "worker": "deep",
        "result": "买入 AAPL 目标价: $12",
        "ts": time.time(),
    }
    assert signal_blocked(fake["result"])
    assert project_work_card(fake) is None
    br = MemoryBridge(store, dest=SELFTEST_NODE)
    r3 = br.offer(fake)
    out["d3_offer"] = r3
    out["d3"] = "green" if r3.get("status") == "rejected" else "red"

    # D4 identity: research role does not mint a model name
    line = project_work_card({
        "receipt_id": "E-tag", "mid": "M-tag", "worker": "research", "result": "ok",
    })
    out["d4"] = "green" if line and "producer_model_id=unknown" in line and "DeepSeek" not in line else "red"

    # D2 isolated selftest + idempotent
    rid = f"selftest-{uuid.uuid4().hex[:10]}"
    rec = {
        "receipt_id": rid, "mid": "M-selftest", "worker": "deep",
        "lane": "scout", "result": "isolated hop", "ts": time.time(),
        "test_run_id": rid,
    }
    a = br.offer(rec)
    b = br.offer(rec)
    out["d2_first"] = a.get("status")
    out["d2_replay"] = b.get("status")
    # production shared must not get this receipt
    prod = store.get_bridge_outbox(rid, SHARED_NODE, "v1")
    out["d2"] = "green" if a.get("status") in {"delivered", "pending"} and b.get("status") == "idempotent" and not prod else "red"

    # D9 decide/verdict on selftest only
    d9a = br.offer({"receipt_id": f"decide:{rid}", "mid": "M-selftest", "text": "fixture decide"}, kind="决定")
    d9b = br.offer({"receipt_id": f"verdict:{rid}", "mid": "M-selftest", "text": "fixture miss"}, kind="终判")
    out["d9_offers"] = [d9a.get("status"), d9b.get("status")]
    out["d9"] = "green" if d9a.get("status") in {"delivered", "idempotent"} and d9b.get("status") in {"delivered", "idempotent"} else "red"

    # D8 EGRESS deny fixture — no live mission, no spend
    try:
        from harness.tool_loop import EGRESS_PATH, format_tool_result
        from harness.web_fetch_v3 import fetch as wf
        # * 开放网不含 gardener → 越 EGRESS,Denied before network
        fr = wf("https://example.com/", "gardener", egress_path=EGRESS_PATH)
        blob = format_tool_result(fr)
        out["d8_blob"] = blob[:240]
        out["d8"] = "green" if ("DENIED" in blob or fr.get("ok") is False) and "reason=" in blob else "red"
    except Exception as e:
        out["d8_err"] = type(e).__name__
        out["d8"] = "red"

    after = snapshot_forbidden()
    out["d5_after"] = after
    deltas = {}
    ok5 = True
    for k, v in before.items():
        if v < 0 or after.get(k, -1) < 0:
            deltas[k] = "unknown"
            if k in ("field-particle", "workbench-b11", "diary"):
                ok5 = False
        else:
            deltas[k] = after[k] - v
            if k in ("field-particle", "workbench-b11", "diary", "cloud-glm52", "cloud-kimi", "cloud-deepseek") and deltas[k] != 0:
                ok5 = False
    out["d5_delta"] = deltas
    out["d5"] = "green" if ok5 else "red"
    return out


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
