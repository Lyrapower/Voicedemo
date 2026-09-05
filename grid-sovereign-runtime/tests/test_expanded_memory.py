"""Unit tests — expanded memory sanitizer."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

GATEWAY_DIR = Path(__file__).resolve().parents[1] / "gateway"
DEMO_ROOT = GATEWAY_DIR.parent.parent
sys.path.insert(0, str(DEMO_ROOT))
sys.path.insert(0, str(GATEWAY_DIR))

from expanded_memory import select_store_memory_snippets  # noqa: E402


class ExpandedMemoryTests(unittest.TestCase):
    def test_blocks_absolute_path_memory(self):
        msgs = [
            {"role": "user", "content": "记住 /Users/me/secret/plan.md 里的要点"},
            {"role": "assistant", "content": "好的"},
        ]
        snippets, hits = select_store_memory_snippets(msgs, task="plan")
        self.assertEqual(snippets, [])
        self.assertTrue(hits)

    def test_keeps_clean_snippet(self):
        msgs = [{"role": "user", "content": "Grid 粒子层只是装饰"}]
        snippets, hits = select_store_memory_snippets(msgs, task="粒子")
        self.assertEqual(len(snippets), 1)
        self.assertFalse(hits)


if __name__ == "__main__":
    unittest.main()
