"""Tests — GLM 5.2 Cloud candidate backend."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from code_task.backends.glm52_cloud import execute_candidate, shadow_candidate_response  # noqa: E402


class FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, payload: dict | None = None):
        self.payload = payload or {
            "model": "glm-5.2:cloud",
            "message": {
                "content": "hello from glm",
                "thinking": "hidden reasoning chain",
            },
            "done_reason": "stop",
            "usage": {"prompt_eval_count": 10, "eval_count": 5},
        }

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, json=None):
        return FakeResponse(self.payload)


class Glm52CandidateBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_injects_glm_identity_system(self):
        captured: dict = {}

        class CaptureClient(FakeClient):
            async def post(self, url, json=None):
                captured["json"] = json
                return await super().post(url, json=json)

        with patch("code_task.backends.glm52_cloud.httpx.AsyncClient", return_value=CaptureClient()):
            await execute_candidate(
                request_id="t0",
                prompt="你是哪个模型？",
                endpoint="http://localhost:11434/api/chat",
                model="glm-5.2:cloud",
            )
        msgs = captured["json"]["messages"]
        self.assertEqual(msgs[0]["role"], "system")
        self.assertIn("GLM-5.2", msgs[0]["content"])
        self.assertNotIn("Kimi K2.6", msgs[0]["content"])

    async def test_execute_strips_thinking(self):
        with patch("code_task.backends.glm52_cloud.httpx.AsyncClient", return_value=FakeClient()):
            resp = await execute_candidate(
                request_id="t1",
                prompt="ping",
                endpoint="http://localhost:11434/api/chat",
                model="glm-5.2:cloud",
            )
        self.assertTrue(resp.ok)
        self.assertEqual(resp.content, "hello from glm")
        self.assertEqual(resp.model, "glm-5.2:cloud")
        self.assertTrue(resp.thinking_meta.present)
        self.assertNotIn("hidden", resp.content)

    async def test_rejects_images(self):
        resp = await execute_candidate(
            request_id="t2",
            prompt="look",
            endpoint="http://localhost:11434/api/chat",
            model="glm-5.2:cloud",
            images=[{"mime": "image/jpeg", "base64": "abc"}],
        )
        self.assertFalse(resp.ok)
        self.assertEqual(resp.done_reason, "input_rejected")

    def test_shadow_accepts_text(self):
        resp = shadow_candidate_response(request_id="s1", prompt="ok")
        self.assertTrue(resp.ok)


if __name__ == "__main__":
    unittest.main()
