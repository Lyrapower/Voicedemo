"""Tests for GLM 5.2 API-equivalent pricing."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from code_task.glm52_pricing import (  # noqa: E402
    enrich_glm52_usage,
    estimate_glm52_cost_usd,
)


class Glm52PricingTests(unittest.TestCase):
    def test_estimate_cost(self):
        usage = {"prompt_tokens": 1_000_000, "completion_tokens": 500_000}
        cost = estimate_glm52_cost_usd(usage)
        self.assertAlmostEqual(cost, 1.40 + 2.20, places=4)

    def test_enrich_usage(self):
        out = enrich_glm52_usage({"prompt_tokens": 100, "completion_tokens": 50})
        self.assertEqual(out["billing"], "api")
        self.assertEqual(out["cost_model"], "glm-5.2")
        self.assertIn("cost_usd", out)


if __name__ == "__main__":
    unittest.main()
