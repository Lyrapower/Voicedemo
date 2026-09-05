"""R4 v2 · IB capital command fail-closed (no live broker)."""
from __future__ import annotations

import unittest

from aether_shared import CAPITAL_DAEMON_COMMANDS, capital_execution_allowed


class CapitalCommandGateTests(unittest.TestCase):
    def test_capital_command_names(self):
        self.assertIn("buy", CAPITAL_DAEMON_COMMANDS)
        self.assertIn("emergency_close", CAPITAL_DAEMON_COMMANDS)
        self.assertNotIn("scan", CAPITAL_DAEMON_COMMANDS)

    def test_dryrun_live_off_denied_even_if_connected(self):
        ok, reason = capital_execution_allowed(
            live=False, scan_source="dryrun", broker_connected=True
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "ib_trading_not_required")

    def test_ib_scan_without_connection_denied(self):
        ok, reason = capital_execution_allowed(
            live=False, scan_source="ib", broker_connected=False
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "ib_not_connected")

    def test_live_and_connected_allowed(self):
        ok, reason = capital_execution_allowed(
            live=True, scan_source="ib", broker_connected=True
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_client_flags_are_not_parameters(self):
        self.assertNotIn("authorized", capital_execution_allowed.__code__.co_varnames)
        self.assertNotIn("benchmark", capital_execution_allowed.__code__.co_varnames)


if __name__ == "__main__":
    unittest.main()
