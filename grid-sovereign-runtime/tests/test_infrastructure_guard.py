"""Tests for grid_infrastructure_guard manifest and runtime verify."""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "config" / "grid_infrastructure_lock.json"
GUARD = ROOT / "scripts" / "grid_infrastructure_guard.py"


class InfrastructureGuardTests(unittest.TestCase):
    def test_lock_manifest_exists(self) -> None:
        self.assertTrue(LOCK.is_file())
        data = json.loads(LOCK.read_text(encoding="utf-8"))
        self.assertIn("frozen_files", data)
        self.assertGreaterEqual(len(data["frozen_files"]), 8)

    def test_runtime_verify_passes_on_clean_tree(self) -> None:
        proc = subprocess.run(
            ["python3", str(GUARD), "verify-runtime"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)

    def test_frozen_includes_identity_and_field_now(self) -> None:
        data = json.loads(LOCK.read_text(encoding="utf-8"))
        keys = set(data["frozen_files"])
        self.assertIn("grid-sovereign-runtime/gateway/aster_identity.py", keys)
        self.assertIn("grid-sovereign-runtime/gateway/field_now_context.py", keys)
        self.assertIn("config/aster_chat_system_prompt.txt", keys)


if __name__ == "__main__":
    unittest.main()
