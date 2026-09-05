"""Unit tests — LM Studio chat vs Ollama coder route selection."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

GATEWAY_DIR = Path(__file__).resolve().parents[1] / "gateway"
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(GATEWAY_DIR))

from substrate_backend import resolve_substrate_target  # noqa: E402


BASE = {
    "backend": "openai",
    "openai_endpoint": "http://localhost:1234/v1",
    "openai_model": "qwen/qwen3.5-9b",
    "ollama_endpoint": "http://localhost:11434/api/chat",
    "ollama_model": "qwen3.5:9b",
    "ollama_coder_model": "qwen2.5-coder:7b",
    "kimi_k25_cloud_model": "kimi-k2.6:cloud",
    "kimi_k25_cloud_endpoint": "http://localhost:11434/api/chat",
    "glm52_cloud_model": "glm-5.2:cloud",
    "glm52_cloud_endpoint": "http://localhost:11434/api/chat",
    "coder_routing_enabled": True,
    "coder_routes": ["compile", "task"],
    "vl_model": "qwen/qwen3.5-9b",
}


class SubstrateBackendTests(unittest.TestCase):
    def test_chat_stays_on_lm_studio(self):
        t = resolve_substrate_target(BASE, route_class="chat")
        self.assertEqual(t.backend_id, "lm_studio")
        self.assertEqual(t.model, "qwen/qwen3.5-9b")
        self.assertFalse(t.coder_routed)

    def test_compile_uses_ollama_coder(self):
        t = resolve_substrate_target(BASE, route_class="compile")
        self.assertEqual(t.backend_id, "ollama_coder")
        self.assertEqual(t.model, "qwen2.5-coder:7b")
        self.assertTrue(t.coder_routed)

    def test_task_uses_ollama_coder(self):
        t = resolve_substrate_target(BASE, route_class="task")
        self.assertEqual(t.backend_id, "ollama_coder")
        self.assertTrue(t.coder_routed)

    def test_gateway_stays_on_lm_studio(self):
        t = resolve_substrate_target(BASE, route_class="gateway")
        self.assertEqual(t.backend_id, "lm_studio")
        self.assertFalse(t.coder_routed)

    def test_vision_never_uses_coder(self):
        t = resolve_substrate_target(BASE, route_class="task", vision=True)
        self.assertEqual(t.backend_id, "lm_studio")
        self.assertFalse(t.coder_routed)

    def test_disabled_coder_routing(self):
        cfg = dict(BASE, coder_routing_enabled=False)
        t = resolve_substrate_target(cfg, route_class="compile", body={})
        self.assertEqual(t.backend_id, "ollama_coder")

    def test_candidate_route_defaults_glm52_cloud(self):
        t = resolve_substrate_target(
            BASE,
            route_class="candidate",
            manual_backend_id="glm52_cloud",
        )
        self.assertEqual(t.backend_id, "glm52_cloud")
        self.assertEqual(t.model, "glm-5.2:cloud")
        self.assertTrue(t.manual)

    def test_candidate_route_kimi_for_vl_internal(self):
        t = resolve_substrate_target(
            BASE,
            route_class="candidate",
            manual_backend_id="kimi_k25_cloud",
        )
        self.assertEqual(t.backend_id, "kimi_k25_cloud")
        self.assertEqual(t.model, "kimi-k2.6:cloud")

    def test_chat_still_lm_studio_with_candidate_body(self):
        t = resolve_substrate_target(
            BASE,
            route_class="chat",
            body={"backend_id": "glm52_cloud"},
        )
        self.assertEqual(t.backend_id, "lm_studio")


if __name__ == "__main__":
    unittest.main()
