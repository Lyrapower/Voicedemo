"""Tests — Kimi candidate adapter strips thinking."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from code_task.backends.kimi_k25_cloud import execute_candidate, shadow_candidate_response  # noqa: E402


class KimiCandidateAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_strips_thinking_from_response(self):
        fake_body = {
            "model": "kimi-k2.6:cloud",
            "done_reason": "stop",
            "message": {
                "role": "assistant",
                "content": "FINAL_ONLY",
                "thinking": "secret chain-of-thought must not leak",
            },
            "usage": {"prompt_tokens": 1, "completion_tokens": 2},
        }

        class FakeResp:
            def raise_for_status(self):
                return None

            def json(self):
                return fake_body

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json):
                return FakeResp()

        with patch("code_task.backends.kimi_k25_cloud.httpx.AsyncClient", return_value=FakeClient()):
            resp = await execute_candidate(
                request_id="rid-1",
                prompt="Say FINAL_ONLY",
                endpoint="http://127.0.0.1:11434/api/chat",
                model="kimi-k2.6:cloud",
            )

        self.assertTrue(resp.ok)
        self.assertEqual(resp.content, "FINAL_ONLY")
        self.assertEqual(resp.role, "candidate")
        self.assertEqual(resp.authority, "none")
        self.assertFalse(resp.memory_write)
        self.assertTrue(resp.thinking_meta.present)
        self.assertGreater(resp.thinking_meta.length, 10)
        dumped = resp.to_dict()
        self.assertNotIn("secret chain-of-thought", str(dumped))
        self.assertNotIn("thinking", dumped)

    async def test_empty_content_is_failure(self):
        fake_body = {
            "message": {"content": "", "thinking": "only thinking"},
            "done_reason": "stop",
        }

        class FakeResp:
            def raise_for_status(self):
                return None

            def json(self):
                return fake_body

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json):
                return FakeResp()

        with patch("code_task.backends.kimi_k25_cloud.httpx.AsyncClient", return_value=FakeClient()):
            resp = await execute_candidate(
                request_id="rid-2",
                prompt="hello",
                endpoint="http://127.0.0.1:11434/api/chat",
                model="kimi-k2.6:cloud",
            )
        self.assertFalse(resp.ok)
        self.assertEqual(resp.content, "")

    def test_shadow_mode_skips_cloud(self):
        resp = shadow_candidate_response(request_id="rid-s", prompt="scoped task only")
        self.assertTrue(resp.ok)
        self.assertIn("shadow", resp.content)


if __name__ == "__main__":
    unittest.main()
