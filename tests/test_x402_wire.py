"""PKG_PRESTART_v6 — x402 adapters. Gate never True; ACK is not harness-shared."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "harness_resident"))


class TestX402Wire(unittest.TestCase):
    def test_gate_never_true(self):
        from harness.x402_wire import resource_gate_adapter

        ctx = dict(
            agent="scout",
            amount_units=1_000_000,
            currency="USD",
            payee="p",
            mission="m",
            action="pay",
            request_id="r1",
        )
        self.assertIs(resource_gate_adapter("m:pay:" + "h" * 16, ctx), False)
        self.assertIs(resource_gate_adapter(None, ctx), False)
        self.assertIs(resource_gate_adapter("tok", {}), False)

    def test_missing_state_path_denies(self):
        from harness.x402_policy import X402Policy
        from harness.x402_wire import make_policy, resource_gate_adapter

        x = X402Policy(make_policy(), gate=resource_gate_adapter, state_path=None)
        self.assertEqual(
            x.authorize("scout", 1, "p", "m", "pay", "m:pay:" + "h" * 16, request_id="r-missing"),
            ("DENY", "durable_state_required"),
        )

    def test_memory_path_denies(self):
        from harness.x402_policy import X402Policy
        from harness.x402_wire import make_policy, resource_gate_adapter

        x = X402Policy(make_policy(), gate=lambda t, c: True, state_path=":memory:")
        self.assertEqual(
            x.authorize("scout", 1, "p", "m", "pay", "tok", request_id="r-mem"),
            ("DENY", "durable_state_required"),
        )

    def test_provenance_ack_stays_pending(self):
        from harness.x402_policy import X402Policy
        from harness.x402_wire import ProvenanceAdapter, make_policy, resource_gate_adapter

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "x402.sqlite")
        x = X402Policy(
            make_policy(),
            gate=resource_gate_adapter,
            state_path=path,
            provenance=ProvenanceAdapter(),
        )
        self.assertEqual(
            x.authorize("scout", 1, "p", "m", "pay", "m:pay:" + "h" * 16, request_id="r-pend"),
            ("DENY", "token_not_bound"),
        )
        flushed = x.flush_provenance()
        self.assertEqual(flushed.get("status"), "pending")
        self.assertIs(ProvenanceAdapter().record_action(event_id="x", mission="m"), None)


if __name__ == "__main__":
    unittest.main()
