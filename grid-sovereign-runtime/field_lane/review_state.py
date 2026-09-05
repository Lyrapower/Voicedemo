"""Review decision ledger — single authority (DISTILL REVIEW GATE spec v1)."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Literal

from field_lane.distill_record import RECORDS_PATH, append_jsonl, load_record, load_records

ReviewStatus = Literal["pending", "approved", "rejected", "held"]

_REPO = Path(__file__).resolve().parents[2]
_DEFAULT_DIR = _REPO / "traces" / "distill"
DECISIONS_PATH = Path(
    os.environ.get("DISTILL_REVIEW_DECISIONS_PATH", str(_DEFAULT_DIR / "review_decisions.jsonl"))
)
DEFAULT_REVIEWER = os.environ.get("DISTILL_REVIEWER", "lyra").strip() or "lyra"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def iter_decisions(*, path: Path | None = None) -> list[dict[str, Any]]:
    p = path or DECISIONS_PATH
    if not p.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def decisions_for(record_id: str, *, path: Path | None = None) -> list[dict[str, Any]]:
    return [d for d in iter_decisions(path=path) if d.get("record_id") == record_id]


def resolve_status(record_id: str, *, decisions_path: Path | None = None) -> ReviewStatus:
    """Current review status — pending if no decisions."""
    decisions = decisions_for(record_id, path=decisions_path)
    if not decisions:
        return "pending"

    def sort_key(d: dict[str, Any]) -> tuple[str, int]:
        return (str(d.get("decided_at") or ""), int(d.get("review_version") or 0))

    latest = max(decisions, key=sort_key)
    status = str(latest.get("status") or "pending").lower()
    if status in ("approved", "rejected", "held"):
        return status  # type: ignore[return-value]
    return "pending"


def resolve_history(record_id: str, *, decisions_path: Path | None = None) -> list[dict[str, Any]]:
    rows = decisions_for(record_id, path=decisions_path)
    return sorted(rows, key=lambda d: (str(d.get("decided_at") or ""), int(d.get("review_version") or 0)))


def append_decision(
    record_id: str,
    status: ReviewStatus,
    *,
    reason: str = "",
    decided_by: str | None = None,
    via: str = "cli",
    decisions_path: Path | None = None,
    records_path: Path | None = None,
) -> dict[str, Any]:
    """Append-only review decision; never mutates distill JSONL."""
    if status in ("rejected", "held") and not (reason or "").strip():
        raise ValueError(f"reason required for status={status}")
    if load_record(record_id, path=records_path) is None:
        raise KeyError(f"record_id not found: {record_id}")

    history = decisions_for(record_id, path=decisions_path)
    version = max((int(d.get("review_version") or 0) for d in history), default=0) + 1
    row: dict[str, Any] = {
        "record_id": record_id,
        "status": status,
        "decided_by": decided_by or DEFAULT_REVIEWER,
        "decided_at": now_iso(),
        "reason": (reason or "").strip(),
        "review_version": version,
        "via": via,
    }
    append_jsonl(decisions_path or DECISIONS_PATH, row)
    return row


def queue_rows(
    *,
    status_filter: ReviewStatus | None = "pending",
    on_date: str | None = None,
    limit: int = 50,
    records_path: Path | None = None,
    decisions_path: Path | None = None,
) -> list[dict[str, Any]]:
    from field_lane.distill_record import coach_comment_preview, fable_grade

    rows: list[dict[str, Any]] = []
    for rec in load_records(on_date=on_date, path=records_path):
        rid = str(rec.get("record_id") or "")
        if not rid:
            continue
        st = resolve_status(rid, decisions_path=decisions_path)
        if status_filter == "pending" and st not in ("pending",):
            continue
        if status_filter == "held" and st != "held":
            continue
        if status_filter and status_filter not in ("pending", "held") and st != status_filter:
            continue
        rows.append(
            {
                "record_id": rid,
                "date": (rec.get("compile_ts") or "")[:10],
                "node_id": rec.get("node_id"),
                "grade": fable_grade(rec),
                "preview": coach_comment_preview(rec),
                "status": st,
                "record": rec,
            }
        )
    rows.sort(key=lambda r: (r.get("date") or "", r.get("record_id") or ""))
    return rows[: max(1, limit)]


def stats_summary(*, on_date: str | None = None, records_path: Path | None = None, decisions_path: Path | None = None) -> dict[str, Any]:
    counts: dict[str, int] = {"pending": 0, "approved": 0, "rejected": 0, "held": 0}
    rejection_reasons: list[str] = []
    for rec in load_records(on_date=on_date, path=records_path):
        rid = str(rec.get("record_id") or "")
        if not rid:
            continue
        st = resolve_status(rid, decisions_path=decisions_path)
        counts[st] = counts.get(st, 0) + 1
        if st == "rejected":
            hist = resolve_history(rid, decisions_path=decisions_path)
            if hist:
                reason = str(hist[-1].get("reason") or "").strip()
                if reason:
                    rejection_reasons.append(reason)

    decided = counts["approved"] + counts["rejected"]
    approval_rate = round(counts["approved"] / decided, 3) if decided else 0.0
    return {
        "counts": counts,
        "total_records": sum(counts.values()),
        "approval_rate": approval_rate,
        "approval_rate_definition": (
            "approved / (approved + rejected) using current resolve_status per record; "
            "pending and held are excluded from numerator and denominator"
        ),
        "approval_rate_numerator": counts["approved"],
        "approval_rate_denominator": decided,
        "rejection_reasons": rejection_reasons[:20],
        "records_path": str(records_path or RECORDS_PATH),
        "decisions_path": str(decisions_path or DECISIONS_PATH),
    }
