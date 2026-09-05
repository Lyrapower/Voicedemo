#!/usr/bin/env python3
from __future__ import annotations

import unittest

from field_lane.distill_vocab import (
    apply_vocab_gate,
    scan_coach_vocab,
    smoke_draft_violations,
    smoke_handoff_draft,
    smoke_handoff_instruction,
)
from field_lane.review_state import resolve_status


class DistillVocabTests(unittest.TestCase):
    def test_smoke_fixture_avoids_reserved_names(self) -> None:
        draft = smoke_handoff_draft()
        self.assertEqual(smoke_draft_violations(draft), [])
        self.assertIn("artifact_ref", draft)
        self.assertNotIn("review_status", draft)

    def test_smoke_fixture_flags_reserved_collision(self) -> None:
        bad = '{"review_status":"pending_review","record_id":"x"}'
        hits = smoke_draft_violations(bad)
        self.assertIn("review_status", hits)
        self.assertIn("record_id", hits)

    def test_scan_catches_pending_review(self) -> None:
        coach = {
            "minimal_correction": (
                '{"artifact_ref":"smoke-0001","compile_marker":"2026-07-16T00:00:00Z",'
                '"gate_phase":"pending_review"}'
            )
        }
        hits = scan_coach_vocab(coach, coach["minimal_correction"])
        self.assertTrue(any("pending_review" in h for h in hits))

    def test_scan_allows_legal_gate_phase_pending(self) -> None:
        coach = {"gate_phase": "pending"}
        self.assertEqual(scan_coach_vocab(coach), [])

    def test_apply_vocab_gate_auto_holds(self) -> None:
        import json
        import os
        import tempfile
        from pathlib import Path

        import field_lane.distill_record as dr
        import field_lane.review_state as rs

        tmp = Path(tempfile.mkdtemp())
        rec = tmp / "r.jsonl"
        dec = tmp / "d.jsonl"
        os.environ["DISTILL_RECORDS_PATH"] = str(rec)
        os.environ["DISTILL_REVIEW_DECISIONS_PATH"] = str(dec)
        dr.RECORDS_PATH = rec
        rs.DECISIONS_PATH = dec

        row = dr.write_record(
            node_id="field-compile",
            compile_ts="2026-07-17T01:00:00-07:00",
            instruction=smoke_handoff_instruction(),
            student_draft=smoke_handoff_draft(),
            coach={"gate_phase": "pending_review"},
            path=rec,
        )
        hits = apply_vocab_gate(row["record_id"], {"gate_phase": "pending_review"}, records_path=rec, decisions_path=dec)
        self.assertIsNotNone(hits)
        self.assertEqual(resolve_status(row["record_id"], decisions_path=dec), "held")


if __name__ == "__main__":
    unittest.main()
