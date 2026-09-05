"""Cloud tab attachments — preprocess + GLM M3 eyes / DeepSeek Kimi VL."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code_task.cloud_attachments import preprocess_cloud_attachments  # noqa: E402


def _m3_eyes_payload(text: str = "红柱三根 OI 栏是 0"):
    rec = (
        "[眼睛·provenance]\nimage_ref=deadbeef\n---\n[眼睛·m3]\n" + text
    )
    return {
        "blocks": ["[VL:minimax-m3] " + text],
        "records": [rec],
        "inject": "【眼睛·M3 视觉转述 · 非判断】\n" + rec,
        "warnings": [],
        "refs": [{"sha256": "deadbeef", "sha12": "deadbeef", "mime": "image/jpeg", "name": "a.png", "nbytes": 3}],
        "hops": [{"vl_ok": True, "vl_model": "minimax-m3:cloud"}],
        "vl_calls": 1,
        "vl_ok": 1,
        "vl_images": 1,
        "vl_backend": "minimax_m3",
        "vl_model": "minimax-m3:cloud",
    }


class CloudAttachmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_glm52_image_uses_m3_eyes(self):
        body = {
            "messages": [{"role": "user", "content": "what color?"}],
            "images": [{"mime": "image/jpeg", "base64": "abc123"}],
        }
        with patch(
            "code_task.cloud_attachments.describe_images_m3",
            new=AsyncMock(return_value=_m3_eyes_payload("red")),
        ):
            out, meta = await preprocess_cloud_attachments(body, "glm52")

        self.assertNotIn("images", out)
        self.assertIn("非判断", out["messages"][-1]["content"])
        self.assertIn("[眼睛·m3]", out["messages"][-1]["content"])
        self.assertEqual(meta.get("eyes", {}).get("vl_backend"), "minimax_m3")
        self.assertTrue(meta.get("preprocess"))

    async def test_glm_pdf_injects_extracted_text(self):
        body = {
            "messages": [{"role": "user", "content": "summarize pdf"}],
            "assets": [{"kind": "pdf", "name": "doc.pdf", "base64": "JVBERi0="}],
        }
        with patch(
            "expanded_orchestrator.preprocess_assets",
            return_value=([], ["【PDF doc.pdf · 本地抽取】\nhello world"], {"kinds": ["pdf"]}),
        ):
            out, meta = await preprocess_cloud_attachments(body, "glm52")

        self.assertNotIn("assets", out)
        self.assertIn("hello world", out["messages"][-1]["content"])
        self.assertTrue(meta.get("preprocess"))

    async def test_glm53_flash_uses_m3_not_native_pixels(self):
        body = {
            "messages": [{"role": "user", "content": "describe"}],
            "assets": [{"kind": "image", "name": "a.png", "mime": "image/png", "base64": "xyz"}],
        }
        with patch(
            "expanded_orchestrator.preprocess_assets",
            return_value=(
                [{"mime": "image/png", "base64": "xyz"}],
                [],
                {"kinds": ["image"]},
            ),
        ), patch(
            "code_task.cloud_attachments.describe_images_m3",
            new=AsyncMock(return_value=_m3_eyes_payload("chart")),
        ):
            out, meta = await preprocess_cloud_attachments(body, "glm53")

        self.assertNotIn("images", out)
        self.assertIn("[眼睛·m3]", out["messages"][-1]["content"])
        self.assertEqual(meta.get("eyes", {}).get("vl_backend"), "minimax_m3")

    async def test_glm53_full_image_uses_m3_eyes(self):
        body = {
            "messages": [{"role": "user", "content": "see this"}],
            "images": [{"mime": "image/png", "base64": "zzz"}],
        }
        with patch(
            "code_task.cloud_attachments.describe_images_m3",
            new=AsyncMock(return_value=_m3_eyes_payload("chart")),
        ):
            out, meta = await preprocess_cloud_attachments(body, "glm53_full")
        self.assertNotIn("images", out)
        self.assertIn("[眼睛·m3]", out["messages"][-1]["content"])
        self.assertTrue(meta.get("preprocess"))

    async def test_deepseek_image_uses_kimi_vl_bypass(self):
        body = {
            "messages": [{"role": "user", "content": "see this"}],
            "images": [{"mime": "image/png", "base64": "zzz"}],
        }
        with patch(
            "code_task.cloud_attachments.describe_images",
            new=AsyncMock(return_value=(["[VL:k2.6] chart"], [], {"vl_ok": 1})),
        ):
            out, meta = await preprocess_cloud_attachments(body, "deepseek_v4")
        self.assertNotIn("images", out)
        self.assertIn("[VL:k2.6] chart", out["messages"][-1]["content"])
        self.assertTrue(meta.get("preprocess"))


if __name__ == "__main__":
    unittest.main()
