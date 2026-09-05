#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from field_lane.distill_record import at_daily_cap, compute_record_id, write_record
from field_lane.promotion_gate import dry_run_pack, select_eligible
from field_lane.review_state import append_decision, resolve_status


class ReviewGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.rec = self.tmp / "distill_records.jsonl"
        self.dec = self.tmp / "review_decisions.jsonl"
        os.environ["DISTILL_RECORDS_PATH"] = str(self.rec)
        os.environ["DISTILL_REVIEW_DECISIONS_PATH"] = str(self.dec)

    def test_record_id_stable(self) -> None:
        rid = compute_record_id(
            node_id="field-compile",
            compile_ts="2026-07-17T01:00:00-07:00",
            fable_response_hash="abc",
        )
        self.assertEqual(len(rid), 64)

    def test_promotion_excludes_pending(self) -> None:
        a = write_record(
            node_id="field-compile",
            compile_ts="2026-07-17T02:00:00-07:00",
            instruction="a",
            student_draft="b" * 40,
            coach={"x": 1},
            coach_raw="{}",
            path=self.rec,
        )
        write_record(
            node_id="field-compile",
            compile_ts="2026-07-17T02:01:00-07:00",
            instruction="c",
            student_draft="d" * 40,
            coach={"x": 1},
            coach_raw="{}",
            path=self.rec,
        )
        append_decision(a["record_id"], "approved", reason="ok", records_path=self.rec, decisions_path=self.dec)
        pack = dry_run_pack(records_path=self.rec, decisions_path=self.dec)
        self.assertEqual(pack["included_count"], 1)
        self.assertEqual(resolve_status(a["record_id"], decisions_path=self.dec), "approved")

    def test_reject_requires_reason(self) -> None:
        row = write_record(
            node_id="n",
            compile_ts="2026-07-17T03:00:00-07:00",
            instruction="i",
            student_draft="d" * 40,
            skip_reason="budget",
            path=self.rec,
        )
        with self.assertRaises(ValueError):
            append_decision(row["record_id"], "rejected", reason="", records_path=self.rec, decisions_path=self.dec)


if __name__ == "__main__":
    unittest.main()
