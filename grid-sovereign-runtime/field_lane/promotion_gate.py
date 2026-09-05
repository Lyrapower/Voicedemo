"""Capability pack promotion gate — approved records only (spec v1)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from field_lane.distill_record import load_records
from field_lane.review_state import resolve_status


def select_eligible(
    *,
    on_date: str | None = None,
    records_path: Path | None = None,
    decisions_path: Path | None = None,
) -> list[dict[str, Any]]:
    return [
        r
        for r in load_records(on_date=on_date, path=records_path)
        if r.get("record_id") and resolve_status(str(r["record_id"]), decisions_path=decisions_path) == "approved"
    ]


def dry_run_pack(
    *,
    on_date: str | None = None,
    records_path: Path | None = None,
    decisions_path: Path | None = None,
) -> dict[str, Any]:
    all_rows = load_records(on_date=on_date, path=records_path)
    eligible = select_eligible(on_date=on_date, records_path=records_path, decisions_path=decisions_path)
    excluded: dict[str, int] = {}
    eligible_ids = {r["record_id"] for r in eligible}
    for row in all_rows:
        rid = str(row.get("record_id") or "")
        if not rid or rid in eligible_ids:
            continue
        st = resolve_status(rid, decisions_path=decisions_path)
        excluded[st] = excluded.get(st, 0) + 1
    return {
        "included_count": len(eligible),
        "included_record_ids": [r["record_id"] for r in eligible],
        "excluded_by_status": excluded,
        "total_candidates": len(all_rows),
    }


def write_pack_manifest(out_path: Path, *, on_date: str | None = None) -> dict[str, Any]:
    summary = dry_run_pack(on_date=on_date)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary
