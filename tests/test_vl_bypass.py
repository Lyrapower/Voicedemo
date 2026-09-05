"""Tests — K2.6 VL bypass describe_image."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from code_task.candidate_contract import CandidateResponse, ThinkingMeta  # noqa: E402
from code_task.vl_bypass import VL_PREFIX, VL_UNAVAILABLE, describe_image, describe_images  # noqa: E402


class VlBypassTests(unittest.IsolatedAsyncioTestCase):
    async def test_describe_image_prefix(self):
        ok = CandidateResponse(
            request_id="vl1",
            ok=True,
            content="a red circle",
            model="kimi-k2.6:cloud",
            thinking_meta=ThinkingMeta(present=True, length=3, hash="abc"),
        )
        with patch("code_task.vl_bypass.execute_kimi_vl", new=AsyncMock(return_value=ok)):
            text, meta = await describe_image(
                {"mime": "image/jpeg", "base64": "abc"},
                question="describe",
                config={"kimi_k25_cloud_model": "kimi-k2.6:cloud"},
                route_id="r1",
            )
        self.assertTrue(text.startswith(VL_PREFIX))
        self.assertIn("red circle", text)
        self.assertEqual(meta["vl_model"], "kimi-k2.6:cloud")

    async def test_describe_images_fail_soft(self):
        bad = CandidateResponse(request_id="vl2", ok=False, done_reason="upstream_error")
        with patch("code_task.vl_bypass.execute_kimi_vl", new=AsyncMock(return_value=bad)):
            blocks, warnings, meta = await describe_images(
                [{"mime": "image/jpeg", "base64": "abc"}],
                task="what is this",
                config={"kimi_k25_cloud_model": "kimi-k2.6:cloud"},
                route_id="r2",
            )
        self.assertEqual(blocks, [])
        self.assertIn(VL_UNAVAILABLE, warnings)
        self.assertEqual(meta["vl_ok"], 0)


if __name__ == "__main__":
    unittest.main()
