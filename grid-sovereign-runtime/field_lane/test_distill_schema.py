"""Distill skips schema:loose / parse_only chat-path compile artifacts."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from field_lane.distill import should_distill  # noqa: E402
from field_lane.schema import COMPILE_SEMANTICS_PARSE_ONLY, SCHEMA_LOOSE  # noqa: E402


class DistillSchemaFilterTest(unittest.TestCase):
    def test_compile_task_distills_by_default(self):
        self.assertTrue(should_distill("compile_json"))

    def test_loose_schema_skips_auto_distill(self):
        self.assertFalse(should_distill("compile_json", schema=SCHEMA_LOOSE))

    def test_parse_only_skips_auto_distill(self):
        self.assertFalse(
            should_distill("compile_json", compile_semantics=COMPILE_SEMANTICS_PARSE_ONLY)
        )


if __name__ == "__main__":
    unittest.main()
