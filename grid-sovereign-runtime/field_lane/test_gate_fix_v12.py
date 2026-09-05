"""GATE_FIX V1.2 — compile_semantics + allow_draft + test marking."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from field_lane.distill import distill_turn, should_distill  # noqa: E402
from field_lane.schema import (  # noqa: E402
    COMPILE_SEMANTICS_PARSE_ONLY,
    COMPILE_SEMANTICS_STRICT,
    SCHEMA_LOOSE,
    TEST_CONTENT_PREFIX,
)


class CompileSemanticsGateTest(unittest.TestCase):
    def test_strict_auto_eligible(self):
        self.assertTrue(
            should_distill("compile_json", compile_semantics=COMPILE_SEMANTICS_STRICT)
        )

    def test_parse_only_auto_blocked(self):
        self.assertFalse(
            should_distill("compile_json", compile_semantics=COMPILE_SEMANTICS_PARSE_ONLY)
        )

    def test_loose_schema_auto_blocked(self):
        self.assertFalse(should_distill("compile_json", schema=SCHEMA_LOOSE))

    def test_legacy_without_semantics_auto_eligible(self):
        self.assertTrue(should_distill("compile_json"))

    def test_test_marked_auto_blocked(self):
        self.assertFalse(should_distill("compile_json", test=True))
        self.assertFalse(
            should_distill(
                "compile_json",
                content=f"{TEST_CONTENT_PREFIX}hello",
            )
        )

    def test_force_parse_only_without_allow_draft_blocked(self):
        self.assertFalse(
            should_distill(
                "compile_json",
                compile_semantics=COMPILE_SEMANTICS_PARSE_ONLY,
                force=True,
            )
        )

    def test_force_parse_only_with_allow_draft_ok(self):
        self.assertTrue(
            should_distill(
                "compile_json",
                compile_semantics=COMPILE_SEMANTICS_PARSE_ONLY,
                force=True,
                allow_draft=True,
            )
        )

    @patch("field_lane.distill.emit_event")
    @patch("field_lane.distill.enabled", return_value=True)
    def test_distill_rejects_parse_only_force_without_allow_draft(self, _en, emit):
        out = distill_turn(
            "instr",
            "x" * 50,
            task="compile_json",
            node_id="field-compile",
            force=True,
            compile_semantics=COMPILE_SEMANTICS_PARSE_ONLY,
            allow_draft=False,
        )
        self.assertTrue(out.get("skipped"))
        self.assertEqual(out.get("reason"), "parse_only_requires_allow_draft")
        kinds = [c.args[0] for c in emit.call_args_list if c.args]
        self.assertIn("reject", kinds)


if __name__ == "__main__":
    unittest.main()
