"""R4 v2 · store tool filter tags, does not delete source text."""
from __future__ import annotations

import unittest

from code_task.cloud_store_tools import _signal_filter


class SignalFilterTests(unittest.TestCase):
    def test_pass_through_with_tag(self):
        raw = "纪要:有人说买入 AAPL"
        out = _signal_filter(raw)
        self.assertIn("买入", out)
        self.assertIn("execution_authority=NONE", out)

    def test_non_signal_unchanged(self):
        raw = "只谈日记,不谈仓位数字"
        self.assertEqual(_signal_filter(raw), raw)


if __name__ == "__main__":
    unittest.main()
