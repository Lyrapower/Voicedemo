"""Tests — GLM-5.2 input scoping and identity system prompt."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from code_task.glm52_input_scope import (  # noqa: E402
    GLM52_IDENTITY_SYSTEM,
    build_chat_messages,
    build_task_scoped_messages,
)


class Glm52InputScopeTests(unittest.TestCase):
    def test_system_anchors_glm52_not_kimi(self):
        self.assertIn("GLM-5.2", GLM52_IDENTITY_SYSTEM)
        self.assertIn("GLM-4.5", GLM52_IDENTITY_SYSTEM)
        self.assertNotIn("Kimi K2.6", GLM52_IDENTITY_SYSTEM)

    def test_task_scoped_has_glm_system(self):
        msgs = build_task_scoped_messages(prompt="hello", task_label="t")
        self.assertEqual(msgs[0]["role"], "system")
        self.assertIn("GLM-5.2", msgs[0]["content"])
        self.assertNotIn("Kimi K2.6", msgs[0]["content"])

    def test_chat_messages_drop_client_system(self):
        msgs = build_chat_messages([
            {"role": "system", "content": "You are GLM-4.5"},
            {"role": "user", "content": "hi"},
        ])
        self.assertEqual(msgs[0]["role"], "system")
        self.assertIn("GLM-5.2", msgs[0]["content"])
        self.assertEqual(msgs[-1]["content"], "hi")


if __name__ == "__main__":
    unittest.main()
