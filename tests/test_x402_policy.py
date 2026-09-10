"""PKG_PRESTART_v1 step 4 — x402 policy, zero egress."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "harness_resident"))

SURFACE = {"capabilities": [
    {"capability_id": "x402", "status": "declared", "permission": "money_moving"},
], "model_profiles": []}


class TestX402Policy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.tmp.name, "prov.jsonl")
        os.environ["HARNESS_PROVENANCE_LOG"] = self.log
        from harness.x402_policy import reset_spent
        reset_spent()

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("HARNESS_PROVENANCE_LOG", None)

    def _tok(self, mission: str, action: str) -> str:
        return f"{mission}:{action}:{'h' * 16}"

    def test_default_config_denies(self):
        from harness.x402_policy import X402Config, authorize
        r = authorize("scout", 1, "payee-a", "M-1", "pay", cfg=X402Config(),
                      authorization_token=self._tok("M-1", "pay"), surface=SURFACE)
        self.assertEqual(r["decision"], "DENY")

    def test_sixth_tx_hits_daily_cap(self):
        from harness.x402_policy import X402Config, authorize
        cfg = X402Config(daily_limit=100, per_tx_limit=20, payees=("p1",),
                         agents={"scout": {"daily_limit": 100, "per_tx_limit": 20}})
        last = None
        for i in range(6):
            last = authorize("scout", 20, "p1", f"M-{i}", f"a{i}", cfg=cfg,
                             authorization_token=self._tok(f"M-{i}", f"a{i}"), surface=SURFACE)
        self.assertEqual(last["decision"], "DENY")
        self.assertEqual(last["reason"], "daily_cap")

    def test_payee_not_whitelisted(self):
        from harness.x402_policy import X402Config, authorize
        cfg = X402Config(daily_limit=100, per_tx_limit=20, payees=("only",),
                         agents={"scout": {"daily_limit": 100, "per_tx_limit": 20}})
        r = authorize("scout", 10, "other", "M-w", "pay", cfg=cfg,
                      authorization_token=self._tok("M-w", "pay"), surface=SURFACE)
        self.assertEqual(r["decision"], "DENY")
        self.assertEqual(r["reason"], "payee_not_whitelisted")

    def test_no_human_token_denied(self):
        from harness.x402_policy import X402Config, authorize
        cfg = X402Config(daily_limit=100, per_tx_limit=20, payees=("p1",),
                         agents={"scout": {"daily_limit": 100, "per_tx_limit": 20}})
        r = authorize("scout", 10, "p1", "M-t", "pay", cfg=cfg,
                      authorization_token=None, surface=SURFACE)
        self.assertEqual(r["decision"], "DENY")
        self.assertEqual(r["reason"], "no_human_token")

    def test_provenance_hash_chain(self):
        from harness.x402_policy import X402Config, authorize
        cfg = X402Config(daily_limit=100, per_tx_limit=20, payees=("p1",),
                         agents={"scout": {"daily_limit": 100, "per_tx_limit": 20}})
        authorize("scout", 10, "p1", "M-h", "pay", cfg=cfg,
                  authorization_token=self._tok("M-h", "pay"), surface=SURFACE)
        rows = [json.loads(l) for l in open(self.log, encoding="utf-8") if l.strip()]
        self.assertGreaterEqual(len(rows), 2)
        prev = ""
        for row in rows:
            self.assertEqual(row.get("prev_hash"), prev)
            self.assertTrue(row.get("event_hash"))
            prev = row["event_hash"]


if __name__ == "__main__":
    unittest.main()
