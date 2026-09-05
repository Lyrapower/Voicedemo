"""Unit tests — factory_task_router prompts (no gateway / no LLM)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gateway"))

from factory_task_router import build_factory_task, map_factory_route, parse_factory_result


class FactoryTaskRouterTest(unittest.TestCase):
    def test_propose_task(self):
        t = build_factory_task("propose", {"idea": "5m momentum"})
        self.assertIn("因子提案", t)
        self.assertIn("5m momentum", t)
        self.assertNotIn("glm", t.lower())

    def test_parse_code_and_hypothesis(self):
        text = "假设说明: short-term reversal\n```python\ndef factor(df):\n    return df['c']\n```"
        out = parse_factory_result("propose", text)
        self.assertIn("def factor", out["code"])
        self.assertIn("reversal", out["hypothesis"])

    def test_map_route(self):
        self.assertEqual(map_factory_route("local"), "local")
        self.assertEqual(map_factory_route("glm52_cloud"), "extended")


if __name__ == "__main__":
    unittest.main()
