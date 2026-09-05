#!/usr/bin/env python3
"""Distill review CLI — DISTILL REVIEW GATE spec v1 (2026-07-17)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_RUNTIME = _ROOT / "grid-sovereign-runtime"
if str(_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_RUNTIME))

from field_lane.distill_record import coach_comment_preview, fable_grade, load_record  # noqa: E402
from field_lane.review_state import (  # noqa: E402
    append_decision,
    queue_rows,
    resolve_history,
    resolve_status,
    stats_summary,
)


def cmd_queue(args: argparse.Namespace) -> int:
    status = args.status or "pending"
    rows = queue_rows(status_filter=status, on_date=args.date, limit=args.limit)
    for row in rows:
        rid = str(row["record_id"])
        print(
            f"{rid[:8]} | {row.get('date') or '—'} | {row.get('node_id') or '—'} | "
            f"{row.get('grade') or '—'} | {row.get('preview') or ''} | {row.get('status')}"
        )
    if not rows:
        print("(empty queue)")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    rec = load_record(args.record_id)
    if not rec:
        print(f"record not found: {args.record_id}", file=sys.stderr)
        return 1
    st = resolve_status(args.record_id)
    hist = resolve_history(args.record_id)
    print(json.dumps({"record": rec, "current_status": st, "decisions": hist}, ensure_ascii=False, indent=2))
    return 0


def _decide(args: argparse.Namespace, status: str) -> int:
    try:
        row = append_decision(args.record_id, status, reason=args.reason or "", via="cli")
    except (ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    current = resolve_status(args.record_id)
    print(json.dumps({"decision": row, "current_status": current}, ensure_ascii=False, indent=2))
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    return _decide(args, "approved")


def cmd_reject(args: argparse.Namespace) -> int:
    if not (args.reason or "").strip():
        print("reject requires -m/--reason", file=sys.stderr)
        return 1
    return _decide(args, "rejected")


def cmd_hold(args: argparse.Namespace) -> int:
    if not (args.reason or "").strip():
        print("hold requires -m/--reason", file=sys.stderr)
        return 1
    return _decide(args, "held")


def cmd_stats(args: argparse.Namespace) -> int:
    print(json.dumps(stats_summary(on_date=args.date), ensure_ascii=False, indent=2))
    return 0


def cmd_selftest(_: argparse.Namespace) -> int:
    import os
    import tempfile

    from field_lane import distill_record, review_state
    from field_lane.distill_record import write_record
    from field_lane.promotion_gate import select_eligible

    tmp = Path(tempfile.mkdtemp())
    rec_path = tmp / "distill_records.jsonl"
    dec_path = tmp / "review_decisions.jsonl"
    os.environ["DISTILL_RECORDS_PATH"] = str(rec_path)
    os.environ["DISTILL_REVIEW_DECISIONS_PATH"] = str(dec_path)
    os.environ["FIELD_DISTILL_DAILY_CAP"] = "0"
    distill_record.RECORDS_PATH = rec_path
    review_state.DECISIONS_PATH = dec_path
    distill_record.DAILY_CAP = 0

    row = write_record(
        node_id="field-compile",
        compile_ts="2026-07-17T12:00:00-07:00",
        instruction="compile_json test",
        student_draft="x" * 40,
        coach={"failure_type": "none", "better_move": "ok"},
        coach_raw='{"failure_type":"none"}',
    )
    rid = row["record_id"]
    assert resolve_status(rid) == "pending"
    assert queue_rows(status_filter="pending", records_path=rec_path, decisions_path=dec_path)
    append_decision(rid, "approved", reason="ok", records_path=rec_path, decisions_path=dec_path)
    assert resolve_status(rid, decisions_path=dec_path) == "approved"
    append_decision(rid, "rejected", reason="flip test", records_path=rec_path, decisions_path=dec_path)
    assert resolve_status(rid, decisions_path=dec_path) == "rejected"
    append_decision(rid, "approved", reason="re-approve", records_path=rec_path, decisions_path=dec_path)
    assert resolve_status(rid, decisions_path=dec_path) == "approved"
    assert len(resolve_history(rid, decisions_path=dec_path)) == 3

    pending = write_record(
        node_id="field-compile",
        compile_ts="2026-07-17T12:01:00-07:00",
        instruction="pending row",
        student_draft="y" * 40,
        coach={"failure_type": "x"},
        coach_raw="{}",
    )
    eligible = select_eligible(records_path=rec_path, decisions_path=dec_path)
    assert any(r["record_id"] == rid for r in eligible)
    assert not any(r["record_id"] == pending["record_id"] for r in eligible)

    budget = write_record(
        node_id="field-compile",
        compile_ts="2026-07-17T12:02:00-07:00",
        instruction="budget skip",
        student_draft="z" * 40,
        skip_reason="budget",
    )
    assert budget.get("coach") is None
    stats = stats_summary(on_date="2026-07-17", records_path=rec_path, decisions_path=dec_path)
    assert stats["counts"]["approved"] >= 1
    print("PASS: review_cli selftest (spec v1 acceptance subset)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Distill review gate CLI (spec v1)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("queue", help="List records by review status")
    s.add_argument("--status", choices=("pending", "held", "approved", "rejected"))
    s.add_argument("--date", help="YYYY-MM-DD")
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=cmd_queue)

    s = sub.add_parser("show", help="Full record + decision history")
    s.add_argument("record_id")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("approve")
    s.add_argument("record_id")
    s.add_argument("-m", "--reason", default="")
    s.set_defaults(func=cmd_approve)

    s = sub.add_parser("reject")
    s.add_argument("record_id")
    s.add_argument("-m", "--reason", required=True)
    s.set_defaults(func=cmd_reject)

    s = sub.add_parser("hold")
    s.add_argument("record_id")
    s.add_argument("-m", "--reason", required=True)
    s.set_defaults(func=cmd_hold)

    s = sub.add_parser("stats")
    s.add_argument("--date", help="YYYY-MM-DD filter")
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("selftest")
    s.set_defaults(func=cmd_selftest)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
