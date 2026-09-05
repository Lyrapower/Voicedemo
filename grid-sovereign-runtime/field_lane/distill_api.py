"""Shared distill read/review API — CLI, 8790 tab3, 8501 coachPanel."""
from __future__ import annotations

import datetime as dt
from typing import Any

from field_lane.distill import distill_turn
from field_lane.distill_record import (
    DAILY_CAP,
    coach_comment_preview,
    fable_calls_on_date,
    fable_grade,
    load_record,
    load_records,
)
from field_lane.review_state import (
    append_decision,
    queue_rows,
    resolve_history,
    resolve_status,
    stats_summary,
)


def _failure_label(rec: dict[str, Any]) -> str:
    if rec.get("skip_reason"):
        return f"skipped: {rec.get('skip_reason')}"
    coach = rec.get("coach")
    if isinstance(coach, dict):
        return str(coach.get("failure_type") or coach.get("comment") or "")
    return ""


def record_summary(rec: dict[str, Any]) -> dict[str, Any]:
    rid = str(rec.get("record_id") or "")
    meta = rec.get("cli_meta") or {}
    violations = None
    if rid:
        hist = resolve_history(rid)
        for d in reversed(hist):
            reason = str(d.get("reason") or "")
            if reason.startswith("violation:invalid_vocab"):
                violations = reason
                break
    return {
        "record_id": rid,
        "compile_ts": rec.get("compile_ts"),
        "node_id": rec.get("node_id"),
        "task": rec.get("task"),
        "client": rec.get("client"),
        "persona": rec.get("persona"),
        "status": resolve_status(rid) if rid else "pending",
        "grade": fable_grade(rec),
        "preview": coach_comment_preview(rec),
        "failure_type": _failure_label(rec),
        "cost_usd": meta.get("cost_usd"),
        "duration_ms": meta.get("duration_ms"),
        "skip_reason": rec.get("skip_reason"),
        "compile_semantics": rec.get("compile_semantics"),
        "test": rec.get("test"),
        "allow_draft_override": rec.get("allow_draft_override"),
        "coach_json_ok": isinstance(rec.get("coach"), dict),
        "vocab_violation": violations,
        "instruction": rec.get("instruction"),
        "student_draft": rec.get("student_draft"),
        "coach": rec.get("coach"),
        "run_id": rec.get("run_id"),
    }


def daily_budget(*, on_date: str | None = None) -> dict[str, Any]:
    day = on_date or dt.date.today().isoformat()
    rows = load_records(on_date=day)
    cost = 0.0
    for rec in rows:
        meta = rec.get("cli_meta") or {}
        c = meta.get("cost_usd")
        if c is not None:
            cost += float(c)
    skips = sum(1 for r in rows if r.get("skip_reason") == "budget")
    calls = fable_calls_on_date(day)
    remaining = max(0, DAILY_CAP - calls)
    return {
        "date": day,
        "calls": calls,
        "daily_cap": DAILY_CAP,
        "estimated_cost_usd": round(cost, 4),
        "skips": skips,
        "cap_remaining": remaining,
        "at_cap": calls >= DAILY_CAP,
    }


def inbox_list(
    *,
    status_filter: str = "pending",
    on_date: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    rows = load_records(on_date=on_date)
    rows.sort(key=lambda r: str(r.get("compile_ts") or ""), reverse=True)
    summaries = [record_summary(r) for r in rows if r.get("record_id")]
    filt = status_filter if status_filter in ("pending", "held", "approved", "rejected", "all") else "pending"
    if filt != "all":
        summaries = [s for s in summaries if s.get("status") == filt]
    stats = stats_summary(on_date=on_date)
    counts = dict(stats.get("counts") or {})
    counts["all"] = int(stats.get("total_records") or sum(counts.values()))
    page = summaries[offset : offset + max(1, limit)]
    return {
        "rows": page,
        "total": len(summaries),
        "offset": offset,
        "limit": limit,
        "filter": filt,
        "counts": counts,
        "budget": daily_budget(on_date=on_date),
    }


def list_queue(
    *,
    status: str | None = "pending",
    on_date: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    filt = status if status in ("pending", "held", "approved", "rejected") else "pending"
    rows = queue_rows(status_filter=filt, on_date=on_date, limit=limit)
    out: list[dict[str, Any]] = []
    for row in rows:
        rec = row.get("record") or {}
        out.append(record_summary(rec))
    return out


def get_record_detail(record_id: str) -> dict[str, Any] | None:
    rec = load_record(record_id)
    if not rec:
        return None
    return {
        **record_summary(rec),
        "coach_raw": rec.get("coach_raw"),
        "cli_meta": rec.get("cli_meta"),
        "decisions": resolve_history(record_id),
    }


def post_review(
    record_id: str,
    status: str,
    *,
    reason: str = "",
    via: str = "api",
) -> dict[str, Any]:
    if status not in ("approved", "rejected", "held"):
        raise ValueError("status must be approved|rejected|held")
    row = append_decision(record_id, status, reason=reason, via=via)
    return {"decision": row, "current_status": resolve_status(record_id)}


def recent_records(*, limit: int = 10, on_date: str | None = None) -> list[dict[str, Any]]:
    rows = load_records(on_date=on_date)
    rows.sort(key=lambda r: str(r.get("compile_ts") or ""), reverse=True)
    return [record_summary(r) for r in rows[: max(1, limit)]]


def latest_compile_pair() -> dict[str, str]:
    rows = load_records()
    rows.sort(key=lambda r: str(r.get("compile_ts") or ""), reverse=True)
    for rec in rows:
        if rec.get("test"):
            continue
        if rec.get("task") in ("compile_json", "handoff_protocol") or rec.get("node_id") == "field-compile":
            return {
                "instruction": str(rec.get("instruction") or ""),
                "draft": str(rec.get("student_draft") or ""),
                "record_id": str(rec.get("record_id") or ""),
                "semantics": str(rec.get("compile_semantics") or ""),
            }
    return {"instruction": "", "draft": "", "record_id": "", "semantics": ""}


def run_coach_sync(
    *,
    instruction: str,
    draft: str,
    task: str = "compile_json",
    node_id: str = "field-compile",
    client: str = "app",
    persona: str | None = None,
    force: bool = True,
    compile_semantics: str | None = None,
    allow_draft: bool = False,
    test: bool | None = None,
) -> dict[str, Any]:
    result = distill_turn(
        instruction,
        draft,
        task=task,
        node_id=node_id,
        persona=persona,
        client=client,
        force=force,
        compile_semantics=compile_semantics,
        allow_draft=allow_draft,
        test=test,
    )
    rid = result.get("record_id")
    if rid:
        detail = get_record_detail(str(rid))
        return {"ok": True, **result, "record": detail}
    return {"ok": not result.get("skipped"), **result}


def events_snapshot(*, source: str = "field_distill", limit: int = 30) -> list[dict[str, Any]]:
    """Read recent store events if grid_store available — optional for callers with store."""
    return []
