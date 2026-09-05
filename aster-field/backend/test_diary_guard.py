"""Regression: diary_guard must not block Grid 22:30 diary body."""
from __future__ import annotations

import unittest

from diary_guard import reject_probe_text, require_scheduler_writer


class DiaryGuardTests(unittest.TestCase):
    def test_scheduler_header_required(self):
        with self.assertRaises(PermissionError):
            require_scheduler_writer(None)
        require_scheduler_writer("aster-scheduler")

    def test_grid_diary_date_header_allowed(self):
        text = (
            "2026-07-18 日记：\n"
            "空在 22:30 后并没有消失，只是折叠了。\n"
            "我在空的边缘，守着这份密度。"
        )
        reject_probe_text(text, what="diary entry")  # must not raise

    def test_agent_probe_still_blocked(self):
        with self.assertRaises(ValueError):
            reject_probe_text("grid-write-probe", what="diary entry")
        with self.assertRaises(ValueError):
            reject_probe_text("acceptance-test entry", what="diary entry")


if __name__ == "__main__":
    unittest.main()
