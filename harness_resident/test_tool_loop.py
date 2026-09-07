#!/usr/bin/env python3
from __future__ import annotations
import sys, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


class ToolLoopTests(unittest.TestCase):
    def test_parse_fence_and_goal_url(self):
        from harness.tool_loop import collect_fetch_urls
        text = "```tool\nname: web.fetch\nurl: https://efts.sec.gov/\n```\n"
        urls = collect_fetch_urls("also https://example.com/a", text)
        self.assertEqual(urls[0], "https://efts.sec.gov/")
        self.assertIn("https://example.com/a", urls)

    def test_format_denied(self):
        from harness.tool_loop import format_tool_result
        s = format_tool_result({"ok": False, "status": "DENIED", "reason": "x", "source_url": "https://x"})
        self.assertIn("DENIED", s)


if __name__ == "__main__":
    unittest.main()
