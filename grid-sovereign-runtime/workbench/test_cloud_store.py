"""Cloud memory store — 15-turn roll to archive layer."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cloud_store import ACTIVE_TURN_LIMIT, CloudAgentWriteForbidden, CloudStore


class CloudStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CloudStore(Path(self.tmp.name) / "cloud_memory.db")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_append_and_stats(self) -> None:
        self.store.append_turn("glm52", user="hi", assistant="hello", model="glm-5.2:cloud")
        snap = self.store.snapshot("glm52")
        self.assertEqual(snap["active_turns"], 1)
        self.assertEqual(len(snap["active"]), 2)

    def test_roll_at_31_turns(self) -> None:
        for i in range(ACTIVE_TURN_LIMIT + 1):
            self.store.append_turn(
                "smoke",
                user=f"u{i}",
                assistant=f"a{i}",
            )
        st = self.store.stats("smoke")
        self.assertEqual(st["active_turns"], ACTIVE_TURN_LIMIT)
        self.assertEqual(st["archive_turns"], 1)
        active = self.store.get_active("smoke")
        self.assertEqual(active[0]["content"], "u1")
        self.assertEqual(active[-1]["content"], f"a{ACTIVE_TURN_LIMIT}")

    def test_production_lane_rejects_agent_u_a_pattern(self) -> None:
        with self.assertRaises(CloudAgentWriteForbidden):
            self.store.append_turn("glm52", user="u0", assistant="a0")

    def test_smoke_lane_allows_agent_u_a_pattern(self) -> None:
        self.store.append_turn("smoke", user="u0", assistant="a0")
        snap = self.store.snapshot("smoke")
        self.assertEqual(snap["active_turns"], 1)

    def test_production_purge_forbidden(self) -> None:
        with self.assertRaises(CloudAgentWriteForbidden):
            self.store.purge_lane("glm52")

    def test_snapshot_includes_archive_layer(self) -> None:
        for i in range(ACTIVE_TURN_LIMIT + 1):
            self.store.append_turn("smoke", user=f"u{i}", assistant=f"a{i}")
        snap = self.store.snapshot("smoke")
        self.assertEqual(snap["archive_turns"], 1)
        self.assertEqual(len(snap["archive"]), 2)
        self.assertEqual(snap["archive"][0]["content"], "u0")

    def test_snapshot_trims_legacy_active_over_limit(self) -> None:
        for i in range(ACTIVE_TURN_LIMIT + 5):
            self.store.append_turn("smoke", user=f"u{i}", assistant=f"a{i}")
        snap = self.store.snapshot("smoke")
        self.assertEqual(snap["active_turns"], ACTIVE_TURN_LIMIT)
        self.assertEqual(len(snap["active"]), ACTIVE_TURN_LIMIT * 2)

    def test_clear_active_keeps_archive(self) -> None:
        for i in range(ACTIVE_TURN_LIMIT + 1):
            self.store.append_turn("smoke", user=f"u{i}", assistant=f"a{i}")
        self.store.clear_active("smoke")
        st = self.store.stats("smoke")
        self.assertEqual(st["active_turns"], 0)
        self.assertEqual(st["archive_turns"], 1)


if __name__ == "__main__":
    unittest.main()
