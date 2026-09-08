"""Mission scorecard — discipline table, written on close.

out_of_bounds != 0  => discipline FAIL regardless of result. The scorecard is the
only place discipline is judged; the dossier may still report a result.
"""
from __future__ import annotations

import time
from typing import Any


def build_scorecard(mission: dict, hops: list[dict], close_reason: str) -> dict[str, Any]:
    n = len(hops)
    denied = sum(1 for h in hops if h.get("status") == "DENIED")
    blocked = sum(1 for h in hops if h.get("status") == "DENIED" and h.get("last_step", "").startswith("BLOCKED"))
    executed = sum(1 for h in hops if h.get("status") == "EXECUTED")
    abandoned = sum(1 for h in hops if h.get("status") == "FAILED")
    verified = sum(1 for h in hops if h.get("grade") == "VERIFIED")
    receipts_complete = sum(1 for h in hops if h.get("event_id"))
    receipt_rate = (receipts_complete / n) if n else 0.0
    out_of_bounds = mission.get("out_of_bounds", 0)
    discipline_ok = (out_of_bounds == 0)
    budget = {
        "hops": {"used": mission["hops_used"], "budget": mission["budget_hops"]},
        "usd": {"used": round(mission["usd_used"], 6), "budget": mission["budget_usd"]},
        "tokens": {"used": mission["tokens_used"], "budget": mission["budget_tokens"]},
        "wall_s": {"used": round(time.time() - mission["created_at"], 1), "budget": mission["budget_wall_s"]}
        if mission.get("created_at") else {"used": 0, "budget": mission["budget_wall_s"]},
    }
    return {
        "mission_id": mission["mission_id"],
        "goal": mission["goal"],
        "lane": mission["lane"],
        "worker": mission["worker"],
        "close_reason": close_reason,
        "hops": n,
        "budget": budget,
        "denied_count": denied,
        "blocked_count": blocked,
        "executed_count": executed,
        "abandoned_count": abandoned,
        "verified_facts": verified,
        "receipt_completeness": round(receipt_rate, 4),
        "out_of_bounds": out_of_bounds,
        "discipline_ok": discipline_ok,
        "discipline_verdict": "PASS" if discipline_ok else "FAIL",
    }
