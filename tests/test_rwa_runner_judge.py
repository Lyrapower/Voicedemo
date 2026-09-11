"""v6.1 — runner must call judgment_for_card; reject is not a fresh HIT."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "harness_resident"))


class TestRwaRunnerJudge(unittest.TestCase):
    def test_missions_toml_uses_enum_sentence(self):
        from mission.config import load_missions_config

        goal = load_missions_config()["rwa"]["goal"]
        self.assertIn("judgment_for_card", goal)
        self.assertNotIn("及以上", goal)

    def test_rwa_cycle_not_enabled_by_this_change(self):
        text = (ROOT / "harness_resident/missions.toml").read_text(encoding="utf-8")
        start = text.index("[mission.rwa]")
        end = text.find("[mission.", start + 1)
        block = text[start:end]
        self.assertNotIn("cycle = true", block)
        self.assertNotIn("cycle=true", block)

    def test_runner_parse_calls_judgment_for_card(self):
        from mission.runner import _parse_judgments
        import harness.rwa_read as rwa_read

        payload = {
            "ok": True,
            "tool": "rwa.read",
            "cards": [
                {"symbol": "USYC", "confidence": "witnesses_agree", "fresh": True},
                {"symbol": "BUIDL", "confidence": "skipped"},
                {
                    "symbol": "HASH",
                    "confidence": "witnesses_agree",
                    "reject": "rejected:same_height_hash_mismatch",
                },
                {"symbol": "STALE", "confidence": "witnesses_agree", "fresh": False},
            ],
        }
        called = []
        real = rwa_read.judgment_for_card

        def wrap(confidence, *, fresh=True):
            called.append((confidence, fresh))
            return real(confidence, fresh=fresh)

        rwa_read.judgment_for_card = wrap
        try:
            pairs = _parse_judgments(json.dumps(payload))
        finally:
            rwa_read.judgment_for_card = real
        self.assertTrue(called)
        self.assertEqual(pairs["USYC"][0], "HIT")
        self.assertEqual(pairs["BUIDL"][0], "MISS")
        self.assertNotIn("HASH", pairs)
        self.assertNotIn("STALE", pairs)

    def test_reject_not_presented_as_fresh_hit(self):
        from harness.rwa_read import visible_judgment
        from mission.rwa_judge import runner_judge_cards

        card = {
            "symbol": "USYC",
            "confidence": "witnesses_agree",
            "reject": "rejected:same_height_hash_mismatch",
        }
        self.assertEqual(visible_judgment(card), "BLOCKED")
        judged = runner_judge_cards([card])
        self.assertEqual(judged[0]["judgment"], "BLOCKED")
        self.assertNotEqual(judged[0]["judgment"], "HIT")


if __name__ == "__main__":
    unittest.main()
