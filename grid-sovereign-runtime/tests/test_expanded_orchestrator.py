"""Unit tests — expanded orchestration helpers."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

GATEWAY_DIR = Path(__file__).resolve().parents[1] / "gateway"
DEMO_ROOT = GATEWAY_DIR.parent.parent
sys.path.insert(0, str(DEMO_ROOT))
sys.path.insert(0, str(GATEWAY_DIR))

from expanded_orchestrator import (  # noqa: E402
    build_envelope,
    classify_task_type,
    needs_cloud_substrate,
    preprocess_assets,
    resolve_budget,
    resolve_expanded_cloud_backend,
    rule_line_for,
    sanitize_outbound,
)


class ExpandedOrchestratorTests(unittest.TestCase):
    def test_normal_task_stays_local(self):
        self.assertEqual(classify_task_type("你好", []), "normal")
        self.assertFalse(needs_cloud_substrate("normal", []))

    def test_reasoning_keyword_routes_heavy_cloud(self):
        task = "请逐步分析是否应该换工作，列出利弊。"
        self.assertEqual(classify_task_type(task, []), "heavy")
        self.assertTrue(needs_cloud_substrate("heavy", []))

    def test_long_text_asset_routes_document(self):
        assets = [{"kind": "text", "name": "notes.md", "text": "x" * 900}]
        self.assertEqual(classify_task_type("总结附件", assets), "document")
        self.assertTrue(needs_cloud_substrate("document", assets))

    def test_image_task_needs_cloud(self):
        assets = [{"kind": "image", "mime": "image/jpeg", "base64": "abc"}]
        self.assertEqual(classify_task_type("看图", assets), "visual")
        self.assertTrue(needs_cloud_substrate("visual", assets))

    def test_pdf_classified_document(self):
        assets = [{"kind": "pdf", "name": "x.pdf", "base64": "JVBERi0="}]
        self.assertEqual(classify_task_type("总结", assets), "document")
        self.assertEqual(resolve_budget("document", {}), 4096)
        _, blocks, _ = preprocess_assets(assets, {})
        self.assertTrue(blocks)

    def test_sanitize_blocks_path(self):
        clean, reason = sanitize_outbound("see /Users/foo/bar.txt")
        self.assertIsNone(clean)
        self.assertIsNotNone(reason)

    def test_build_envelope_has_rule_line(self):
        prompt, summary = build_envelope(
            task="test",
            client_context="用户: hi",
            text_blocks=[],
            memory_snippets=[],
        )
        self.assertIn("Grid 的扩展 substrate", prompt)
        self.assertIn("GLM-5.2", prompt)
        self.assertIn("法则1行", summary)

    def test_build_envelope_glm53_rule(self):
        prompt, _ = build_envelope(
            task="test",
            client_context="",
            text_blocks=[],
            memory_snippets=[],
            cloud_backend="glm53_flash_cloud",
        )
        self.assertIn("GLM-5.3 Flash", prompt)
        self.assertIn("禁止把推理", prompt)
        self.assertIn("GLM-5.3 Flash", rule_line_for("glm53_flash_cloud"))
        # old K2.6 second-base id now aliases to GLM-5.3 Flash
        self.assertIn("GLM-5.3 Flash", rule_line_for("kimi_k25_cloud"))

    def test_resolve_expanded_cloud_backend(self):
        self.assertEqual(resolve_expanded_cloud_backend({}), "glm52_cloud")
        self.assertEqual(
            resolve_expanded_cloud_backend({"cloud_backend": "glm53_flash_cloud"}),
            "glm53_flash_cloud",
        )
        self.assertEqual(
            resolve_expanded_cloud_backend({"cloud_backend": "kimi_k25_cloud"}),
            "glm53_flash_cloud",
        )
        self.assertEqual(
            resolve_expanded_cloud_backend({"backend_id": "kimi"}),
            "glm53_flash_cloud",
        )
        self.assertEqual(
            resolve_expanded_cloud_backend({"cloud_backend": "nope"}),
            "glm52_cloud",
        )

    def test_preprocess_images_named_vl_not_kimi_path(self):
        assets = [{"kind": "image", "mime": "image/jpeg", "base64": "abc"}]
        vl_images, blocks, meta = preprocess_assets(assets, {})
        self.assertEqual(len(vl_images), 1)
        self.assertEqual(meta.get("kinds"), ["image"])


if __name__ == "__main__":
    unittest.main()
