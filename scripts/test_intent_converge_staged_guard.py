"""Unit tests for INTENT_CONVERGE staged-diff guard (no permanent hook)."""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from intent_converge_staged_guard import check_rows  # noqa: E402


class StagedGuardTests(unittest.TestCase):
    def test_whitelist_ok(self) -> None:
        errs = check_rows(
            [("M", "compiler/affect_preserve.py", None),
             ("M", "compiler/test_affect_intent.py", None)],
            "polarity",
            check_symlinks=False,
        )
        self.assertEqual(errs, [])

    def test_reject_foreign(self) -> None:
        errs = check_rows(
            [("A", "alpha-platform/backend/app.py", None)],
            "polarity",
            check_symlinks=False,
        )
        self.assertTrue(any("foreign" in e or "whitelist" in e for e in errs), errs)

    def test_reject_rename(self) -> None:
        errs = check_rows(
            [("R", "compiler/affect_preserve.py", "compiler/x.py")],
            "polarity",
            check_symlinks=False,
        )
        self.assertTrue(any("rename" in e for e in errs), errs)

    def test_reject_outside_whitelist(self) -> None:
        errs = check_rows(
            [("M", "README.md", None)],
            "polarity",
            check_symlinks=False,
        )
        self.assertTrue(any("whitelist" in e for e in errs), errs)

    def test_empty_staged(self) -> None:
        self.assertIn("nothing staged", check_rows([], "polarity"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
