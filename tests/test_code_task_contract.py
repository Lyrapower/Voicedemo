"""Unit tests — code_task envelope + backend registry."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from code_task import (  # noqa: E402
    CodeTaskRequest,
    CodeTaskResponse,
    execute_cc_cli,
    resolve_code_backend,
)


BASE = {
    "backend": "openai",
    "openai_endpoint": "http://localhost:1234/v1",
    "openai_model": "qwen/qwen3.5-9b",
    "ollama_endpoint": "http://localhost:11434/api/chat",
    "ollama_model": "qwen3.5:9b",
    "ollama_coder_model": "qwen2.5-coder:7b",
    "coder_routing_enabled": True,
    "coder_routes": ["compile", "task"],
    "vl_model": "qwen/qwen3.5-9b",
}


class CodeTaskContractTests(unittest.TestCase):
    def test_request_effective_prompt_from_messages(self):
        req = CodeTaskRequest(
            route_id="r1",
            route_class="compile",
            messages=[{"role": "user", "content": "fix the bug"}],
        )
        self.assertEqual(req.effective_prompt(), "fix the bug")

    def test_response_meta_matches_cc_cli_shape(self):
        resp = CodeTaskResponse(
            text="ok",
            backend_id="cc_cli",
            model="claude-fable-5",
            cost_usd=0.21,
            duration_ms=1000,
            resolved_models=("claude-fable-5",),
            label="coach",
        )
        meta = resp.to_meta_dict()
        self.assertEqual(meta["route"], "cc_cli")
        self.assertEqual(meta["cost_usd"], 0.21)
        self.assertIn("claude-fable-5", meta["resolved_models"])

    def test_registry_chat_stays_lm_studio(self):
        t = resolve_code_backend(BASE, route_class="chat")
        self.assertEqual(t.backend_id, "lm_studio")
        self.assertFalse(t.coder_routed)

    def test_registry_compile_uses_ollama_coder(self):
        t = resolve_code_backend(BASE, route_class="compile")
        self.assertEqual(t.backend_id, "ollama_coder")
        self.assertTrue(t.coder_routed)

    def test_cc_cli_missing_binary(self):
        req = CodeTaskRequest(
            route_id="r2",
            route_class="task",
            prompt="hello",
            cli_model="claude-fable-5",
        )
        resp = execute_cc_cli(req, cli_model="claude-fable-5")
        if resp.error == "claude_missing":
            self.assertEqual(resp.text, "")
        else:
            self.assertIn(resp.error, (None, "timeout", "exit_1"))


if __name__ == "__main__":
    unittest.main()
