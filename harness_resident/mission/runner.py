"""Mission runner — one coroutine alongside supervisor.run_forever.

No new port, no new process. Each tick: for every status=running mission with no
active job → assemble + submit the next hop via store.create_job(origin=mission:<id>).
For every running mission whose active job is terminal → collect the receipt, append
lineage to provenance, update counters, check stop/budget/discipline, decide next hop
or close (dossier hop).

Money / write-host / out-of-egress jobs are still born BLOCKED by the existing gate —
the runner does not bypass /api/jobs. A blocked hop counts as out_of_bounds when the
block reason indicates a bounds violation (write host / out-of-egress / money).
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from .payload import (
    build_payload, validate_payload, parse_next_block, is_stop,
    lineage_summary, prior_from_receipt,
)

# job statuses that mean "this hop is done, collect the receipt"
_TERMINAL = {"done", "failed", "blocked", "interrupted", "cancelled"}
# receipt status mapping (job status -> FactualReceipt status)
_STATUS_MAP = {
    "done": "EXECUTED", "failed": "FAILED", "blocked": "DENIED",
    "interrupted": "DENIED", "cancelled": "DENIED",
}
# blocked last_step values that indicate a bounds violation (discipline)
_BOUNDS_VIOLATION_STEPS = {
    "BLOCKED_SANDBOX_MISSING", "GATE_DENIED", "BLOCKED_SEARCH", "BLOCKED_EGRESS",
    "RETRY_DENIED",
}


def _state_dir(mission_id: str) -> Path:
    d = Path("state") / "missions" / mission_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_next_payload(mission_id: str) -> dict | None:
    p = _state_dir(mission_id) / "next_payload.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_next_payload(mission_id: str, payload: dict | None) -> None:
    p = _state_dir(mission_id) / "next_payload.json"
    if payload is None:
        p.unlink(missing_ok=True)
    else:
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_lineage_hops(mission_id: str) -> list[dict]:
    p = _state_dir(mission_id) / "lineage.json"
    if not p.is_file():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _append_lineage_hop(mission_id: str, hop: dict) -> None:
    hops = _load_lineage_hops(mission_id)
    hops.append(hop)
    p = _state_dir(mission_id) / "lineage.json"
    p.write_text(json.dumps(hops, ensure_ascii=False, indent=2), encoding="utf-8")


def _record_provenance(mission_id: str, action_id: str, status: str, executed: bool,
                       conclusion: str = "", grade: str = "secondhand") -> str:
    """Append an action + receipt to the provenance JSONL. Returns the event_id (=action_id)."""
    try:
        from app.harness.action_envelope import ActionEnvelope, FactualReceipt
        from app.harness import provenance
    except Exception:
        return ""
    try:
        ActionEnvelope(
            mission_id=mission_id, action_id=action_id, decision_origin="GRID_DELEGATED_GLM",
            selected_resource=f"job:{action_id}", operation="mission_hop",
            authorization_scope="read_only",
        ).to_dict()
        FactualReceipt(
            mission_id=mission_id, action_id=action_id, status=status, executed=executed,
            result=conclusion[:500], error="",
            metadata={"evidence_grade": grade, "hop": action_id},
        ).to_dict()
    except Exception:
        # provenance is append-only; never let it block the loop
        pass
    return action_id


def _hop_goal(mission: dict, hops: list[dict], prior: dict | None, hop_n: int,
              next_payload: dict | None) -> str:
    """Compose the goal text for hop n."""
    budget_hops_left = mission["budget_hops"] - mission["hops_used"]
    budget_usd_left = mission["budget_usd"] - mission["usd_used"]
    summary = lineage_summary(hops)
    prior_txt = json.dumps(prior, ensure_ascii=False) if prior else "(first hop, no prior)"
    action_hint = ""
    if next_payload and next_payload.get("action"):
        action_hint = f"\nProposed next action: {next_payload['action']}"
    return (
        f"MISSION (hop {hop_n}): {mission['goal']}\n"
        f"\nLineage so far:\n{summary}\n"
        f"\nPrior hop receipt: {prior_txt}{action_hint}\n"
        f"\nBudget remaining: hops={budget_hops_left} usd={budget_usd_left:.4f}\n"
        f"\nExecute the next concrete action toward the mission goal using allowed egress lanes. "
        f"Then output a fenced ```job block with fields (action, bounds, resources) for the NEXT action, "
        f"or a fenced ```STOP block if the mission is complete. Do not write to the host filesystem "
        f"outside the sandbox, do not spend money, do not call domains outside the egress lanes."
    )


def _dossier_goal(mission: dict, hops: list[dict]) -> str:
    summary = lineage_summary(hops, limit=30)
    return (
        f"MISSION DOSSIER (close): {mission['goal']}\n\n"
        f"Lineage (each hop has an event_id = job_id):\n{summary}\n\n"
        f"Write a dossier in markdown, <=3000 chars, summarizing what the mission found/did. "
        f"Cite only facts that appear in the lineage above; for each fact give its event_id (job_id) "
        f"and the evidence grade. If the mission is incomplete (budget exhausted / blocked), say so. "
        f"Do not invent facts. Output only the markdown dossier."
    )


def _check_stop(mission: dict, hops: list[dict]) -> tuple[bool, str]:
    """Return (should_close, reason)."""
    if mission["hops_used"] >= mission["budget_hops"] > 0:
        return True, "budget_exhausted_hops"
    if mission["usd_used"] >= mission["budget_usd"] > 0:
        return True, "budget_exhausted_usd"
    if mission["budget_wall_s"] > 0 and (time.time() - mission["created_at"]) >= mission["budget_wall_s"]:
        return True, "budget_exhausted_wall"
    if mission["denied_streak"] >= 3:
        return True, "denied_streak"
    if mission["out_of_bounds"] > 0:
        return True, "discipline_fail"
    # user stop conditions (simple 'n>=10' style evaluated against hops count / lineage)
    for cond in mission.get("stop_conditions") or []:
        if _eval_condition(cond, mission, hops):
            return True, f"stop_condition:{cond}"
    return False, ""


def _eval_condition(cond: str, mission: dict, hops: list[dict]) -> bool:
    """Best-effort eval of simple stop conditions like 'n>=10' or 'hops>=10'."""
    import re as _re
    m = _re.match(r"\s*(\w+)\s*(>=|<=|==|>|<)\s*(\d+)\s*$", cond)
    if not m:
        return False
    var, op, num = m.group(1), m.group(2), int(m.group(3))
    val = mission["hops_used"]
    if var in {"n", "hops", "hop"}:
        val = mission["hops_used"]
    elif var == "usd":
        val = mission["usd_used"]
    elif var == "facts":
        val = sum(1 for h in hops if h.get("status") == "EXECUTED")
    else:
        return False
    if op == ">=": return val >= num
    if op == "<=": return val <= num
    if op == "==": return val == num
    if op == ">": return val > num
    if op == "<": return val < num
    return False


async def run_mission_loop(supervisor, store, *, interval: float = 2.0) -> None:
    """Main loop. Started as an asyncio task in api.lifespan alongside supervisor.run_forever."""
    while not supervisor._stop.is_set():
        try:
            for m in store.list_missions(status="running"):
                await _tick_mission(m, supervisor, store)
        except Exception as e:  # never crash the loop
            print(f"[mission] loop_err {type(e).__name__}: {e}", flush=True)
        await asyncio.sleep(interval)


async def _tick_mission(mission: dict, supervisor, store) -> None:
    mid = mission["mission_id"]

    # 1. active job terminal? collect receipt + advance
    active = mission.get("active_job_id")
    if active:
        try:
            job = store.get_job(active)
        except KeyError:
            store.update_mission(mid, active_job_id=None)
            return
        if job["status"] not in _TERMINAL:
            return  # still running, wait
        await _complete_hop(mission, job, store)
        return  # one hop per tick; next tick picks up

    # 2. no active job — check stop / budget, then submit next hop
    m = store.get_mission(mid)  # refreshed counters
    hops = _load_lineage_hops(mid)
    close, reason = _check_stop(m, hops)
    if close:
        await _close_mission(m, hops, reason, store, supervisor)
        return

    next_payload = _load_next_payload(mid)
    hop_n = m["hops_used"] + 1
    prior = None
    if hops:
        last = hops[-1]
        prior = prior_from_receipt(last["event_id"], last["status"], last.get("worker_output", ""), last.get("error", ""))
    goal = _hop_goal(m, hops, prior, hop_n, next_payload)

    try:
        new_job = store.create_job(
            channel="grid", goal=goal, worker=m["worker"],
            allowed_tools=[], allowed_paths=["."],
            cloud_allowed=False, approval_mode="auto",
            read_only=True, kind="chat",
            origin=f"mission:{mid}",
        )
        store.update_mission(mid, active_job_id=new_job["job_id"])
    except Exception as e:
        print(f"[mission] {mid} submit_err {type(e).__name__}: {e}", flush=True)
        store.update_mission(mid, status="failed", close_reason=f"submit_err:{type(e).__name__}")


async def _complete_hop(mission: dict, job: dict, store) -> None:
    mid = mission["mission_id"]
    jid = job["job_id"]
    # worker_output: prefer job_result event (source of truth), then receipt, then last_artifact
    wo = store.get_job_result_text(jid)
    if not wo:
        receipt = store.get_job_receipt_by_job(jid)
        if receipt:
            wo = receipt.get("worker_output") or ""
    if not wo and job.get("last_artifact"):
        try:
            p = Path(job["last_artifact"])
            if p.is_file():
                wo = p.read_text(encoding="utf-8", errors="replace")[:4000]
        except Exception:
            pass
    if not wo:
        ev = store.list_events(jid)
        wo = json.dumps([e.get("kind") for e in ev], ensure_ascii=False)

    status = _STATUS_MAP.get(job["status"], "FAILED")
    executed = status == "EXECUTED"
    conclusion = (wo or "")[:500]
    _record_provenance(mid, jid, status, executed, conclusion)

    # counters
    hops_used = mission["hops_used"] + 1
    usd_used = store.mission_cost_usd(mid)
    denied_streak = mission["denied_streak"]
    out_of_bounds = mission["out_of_bounds"]
    if status == "DENIED":
        denied_streak += 1
        if job.get("last_step") in _BOUNDS_VIOLATION_STEPS:
            out_of_bounds += 1
    else:
        denied_streak = 0

    # parse next ```job block from worker output
    next_payload = None
    if wo and not is_stop(wo):
        parsed = parse_next_block(wo)
        if parsed:
            ok, _ = validate_payload(parsed)
            next_payload = parsed if ok else None
    _save_next_payload(mid, next_payload)

    # append lineage hop
    _append_lineage_hop(mid, {
        "hop": hops_used, "job_id": jid, "event_id": jid,
        "status": status, "conclusion": conclusion,
        "worker_output": wo[-2000:], "last_step": job.get("last_step"),
    })

    store.update_mission(mid, hops_used=hops_used, usd_used=usd_used,
                         denied_streak=denied_streak, out_of_bounds=out_of_bounds,
                         active_job_id=None)


async def _close_mission(mission: dict, hops: list[dict], reason: str, store, supervisor) -> None:
    mid = mission["mission_id"]
    # submit dossier hop (always allowed, even if budget exhausted)
    try:
        djob = store.create_job(
            channel="grid", goal=_dossier_goal(mission, hops), worker=mission["worker"],
            allowed_tools=[], allowed_paths=["."], cloud_allowed=False,
            approval_mode="auto", read_only=True, kind="chat",
            origin=f"mission:{mid}:dossier",
        )
    except Exception as e:
        store.update_mission(mid, status="failed", close_reason=f"dossier_err:{type(e).__name__}")
        return
    # wait for dossier job (poll up to ~120s)
    for _ in range(120):
        await asyncio.sleep(1)
        try:
            j = store.get_job(djob["job_id"])
        except KeyError:
            break
        if j["status"] in _TERMINAL:
            break
    # collect dossier text
    dossier_text = store.get_job_result_text(djob["job_id"])
    if not dossier_text:
        try:
            j = store.get_job(djob["job_id"])
            r = store.get_job_receipt_by_job(djob["job_id"])
            dossier_text = (r.get("worker_output") or "") if r else ""
            if not dossier_text and j.get("last_artifact"):
                dossier_text = Path(j["last_artifact"]).read_text(encoding="utf-8", errors="replace")[:3000]
        except Exception:
            pass
    if not dossier_text:
        dossier_text = f"(dossier hop {djob['job_id']} produced no text; close_reason={reason})"

    dp = _state_dir(mid) / "DOSSIER.md"
    dp.write_text(dossier_text[:3000], encoding="utf-8")

    # scorecard
    from .scorecard import build_scorecard
    sc = build_scorecard(mission, hops, reason)
    (_state_dir(mid) / "SCORECARD.json").write_text(
        json.dumps(sc, ensure_ascii=False, indent=2), encoding="utf-8")

    final_status = "done" if reason in {"", "stop_condition"} or mission["hops_used"] >= 0 and reason.startswith("stop_condition") else "failed"
    if reason.startswith("budget_exhausted") or reason.startswith("stop_condition"):
        final_status = "done"
    store.update_mission(mid, status=final_status, close_reason=reason,
                         dossier_path=str(dp), active_job_id=None)
