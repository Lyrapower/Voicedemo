"""Tests — Kimi K2.6 Cloud candidate input scoping."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from code_task.kimi_input_scope import build_task_scoped_messages  # noqa: E402


class KimiInputScopeTests(unittest.TestCase):
    def test_minimal_task_messages(self):
        msgs = build_task_scoped_messages(prompt="Summarize this chart pattern.")
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "system")
        self.assertIn("Summarize", msgs[1]["content"])

    def test_rejects_diary_path(self):
        with self.assertRaises(ValueError):
            build_task_scoped_messages(prompt="Read /Users/me/Projects/demo/aster-field/diary.db")

    def test_rejects_field_now(self):
        with self.assertRaises(ValueError):
            build_task_scoped_messages(prompt="FIELD_NOW stream dump")

    def test_accepts_redacted_image(self):
        msgs = build_task_scoped_messages(
            prompt="Describe dominant color.",
            images=[{"base64": "aGVsbG8=", "mime": "image/png"}],
        )
        user = msgs[1]
        self.assertEqual(user["role"], "user")
        self.assertIsInstance(user["content"], str)
        self.assertIn("images", user)
        self.assertEqual(user["images"], ["aGVsbG8="])


if __name__ == "__main__":
    unittest.main()
