"""Regression: LM Studio Qwen jinja requires dialog to start with non-empty user."""
from __future__ import annotations

import unittest

from chat_history_clean import normalize_substrate_dialog


class SubstrateDialogTests(unittest.TestCase):
    def test_drops_empty_users_and_leading_assistant(self) -> None:
        msgs = [
            {"role": "assistant", "content": "prior error"},
            {"role": "user", "content": ""},
            {"role": "assistant", "content": "x"},
            {"role": "user", "content": "hello"},
        ]
        out, stale = normalize_substrate_dialog(msgs)
        roles = [m["role"] for m in out]
        self.assertEqual(roles[0], "user")
        self.assertIn("hello", [m["content"] for m in out if m["role"] == "user"])
        self.assertTrue(stale)

    def test_keeps_system_then_user(self) -> None:
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "fail card"},
            {"role": "user", "content": "ping"},
        ]
        out, _ = normalize_substrate_dialog(msgs)
        self.assertEqual([m["role"] for m in out], ["system", "user"])


if __name__ == "__main__":
    unittest.main()
