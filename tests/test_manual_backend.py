"""Tests — explicit manual backend_id on compile/task."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from code_task.manual_backend import (  # noqa: E402
    effective_manual_backend_id,
    parse_manual_backend_id,
    substrate_route_class,
    task_scoped_cc_prompt,
)
from code_task.registry import resolve_code_backend  # noqa: E402

BASE = {
    "backend": "openai",
    "openai_endpoint": "http://localhost:1234/v1",
    "openai_model": "qwen/qwen3.5-9b",
    "ollama_endpoint": "http://localhost:11434/api/chat",
    "ollama_coder_model": "qwen2.5-coder:7b",
}


class ManualBackendTests(unittest.TestCase):
    def test_default_compile_is_ollama_coder(self):
        bid = effective_manual_backend_id({}, route_class="compile")
        self.assertEqual(bid, "ollama_coder")
        t = resolve_code_backend(BASE, route_class="compile", body={})
        self.assertEqual(t.backend_id, "ollama_coder")

    def test_explicit_cc_cli(self):
        body = {"backend_id": "cc_cli"}
        self.assertEqual(parse_manual_backend_id(body, route_class="compile"), "cc_cli")
        t = resolve_code_backend(BASE, route_class="compile", body=body)
        self.assertEqual(t.backend_id, "cc_cli")
        self.assertTrue(t.manual)

    def test_cc_cli_model_override_from_body(self):
        body = {"backend_id": "cc_cli", "cli_model": "claude-sonnet-4-6"}
        t = resolve_code_backend(BASE, route_class="task", body=body)
        self.assertEqual(t.backend_id, "cc_cli")
        self.assertEqual(t.model, "claude-sonnet-4-6")

    def test_chat_ignores_backend_id(self):
        self.assertIsNone(parse_manual_backend_id({"backend_id": "cc_cli"}, route_class="chat"))
        t = resolve_code_backend(BASE, route_class="chat", body={"backend_id": "cc_cli"})
        self.assertEqual(t.backend_id, "lm_studio")

    def test_task_hint_from_body(self):
        self.assertEqual(
            substrate_route_class({"task": "compile_json"}, "chat"),
            "compile",
        )

    def test_task_scoped_cc_prompt_strips_history(self):
        msgs = [
            {"role": "system", "content": "compile contract"},
            {"role": "user", "content": "only this task"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "ignored"},
        ]
        p = task_scoped_cc_prompt(msgs, route_class="compile")
        self.assertIn("compile contract", p)
        self.assertIn("only this task", p)
        self.assertNotIn("old answer", p)

    def test_candidate_backend_requires_glm52(self):
        from code_task.manual_backend import parse_candidate_backend_id

        self.assertEqual(parse_candidate_backend_id({"backend_id": "glm52_cloud"}), "glm52_cloud")
        self.assertEqual(
            parse_candidate_backend_id({"backend_id": "glm53_flash_cloud"}),
            "glm53_flash_cloud",
        )
        with self.assertRaises(ValueError):
            parse_candidate_backend_id({})
        with self.assertRaises(ValueError):
            parse_candidate_backend_id({"backend_id": "ollama_coder"})


if __name__ == "__main__":
    unittest.main()
