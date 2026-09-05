"""M3 VL eyes — vision-only, hash citation, persist gate."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code_task.m3_vl_eyes import (  # noqa: E402
    AUDIT_PREFIX,
    EYES_PREFIX,
    M3_SECTION,
    M3_SYSTEM,
    VL_PREFIX,
    format_eyes_record,
    format_glm_audit_record,
    glm_inject_block,
    image_ref,
    persist_allowed,
)


class M3EyesTests(unittest.TestCase):
    def test_image_ref_is_hash_not_pixels(self):
        ref = image_ref({"mime": "image/png", "base64": "aGVsbG8="}, name="k.png")
        self.assertEqual(ref["name"], "k.png")
        self.assertEqual(len(ref["sha256"]), 64)
        self.assertNotIn("base64", ref)
        self.assertNotIn("data", ref)

    def test_m3_prompt_is_vision_only(self):
        self.assertIn("不报判断", M3_SYSTEM)
        self.assertIn("不要判断 OI", M3_SYSTEM)
        self.assertNotIn("做多", M3_SYSTEM)

    def test_provenance_record_searchable(self):
        ref = {"sha256": "abc", "sha12": "abc", "mime": "image/png", "name": "oi.png", "nbytes": 12}
        rec = format_eyes_record(ref, "图上 OI 栏是 0", model="minimax-m3:cloud", route_id="r1")
        self.assertTrue(rec.startswith(EYES_PREFIX))
        self.assertIn(M3_SECTION, rec)
        self.assertIn("image_ref=abc", rec)
        self.assertIn("图上 OI 栏是 0", rec)
        self.assertNotIn("aGVsbG8=", rec)

    def test_glm_audit_links_image_ref(self):
        rec = format_glm_audit_record(
            [{"sha256": "abc"}],
            "这张图 OI=0 与 aether scan 的 missing_in_snapshot 对齐。",
            substrate="glm52",
            route_id="r1",
            glm_model="glm-5.2:cloud",
        )
        self.assertTrue(rec.startswith(AUDIT_PREFIX))
        self.assertIn("image_ref=abc", rec)
        self.assertIn("glm_substrate=glm52", rec)
        self.assertIn("aether scan", rec)

    def test_glm_inject_tells_glm_not_to_treat_m3_as_fact(self):
        block = glm_inject_block(["[眼睛·provenance]\nimage_ref=abc\n---\n[眼睛·m3]\n红柱"])
        self.assertIn("非判断", block)
        self.assertIn("不是已审计事实", block)
        self.assertIn("aether scan", block)

    def test_persist_gate(self):
        self.assertEqual(persist_allowed({"persist": False, "memory_node": "cloud-glm52"}), (False, ""))
        self.assertEqual(persist_allowed({"memory_sealed": True, "memory_node": "sealed"}), (False, ""))
        self.assertEqual(persist_allowed({"memory_node": "workbench-b11"}), (False, ""))
        self.assertEqual(persist_allowed({"memory_node": "field-particle"}), (False, ""))
        self.assertEqual(persist_allowed({"memory_node": "cloud-glm52"}), (True, "cloud-glm52"))
        self.assertEqual(persist_allowed({"memory_node": "smoke_node"}), (True, "smoke_node"))

    def test_persist_eyes_to_temp_store(self):
        import sqlite3
        import tempfile
        from code_task.m3_vl_eyes import persist_eyes_messages

        with tempfile.TemporaryDirectory() as td:
            db = str(Path(td) / "grid_store.db")
            rec = format_eyes_record(
                {"sha256": "ab", "sha12": "ab", "mime": "image/png", "name": "t.png", "nbytes": 1},
                "可见数字 0",
                model="minimax-m3:cloud",
                route_id="t",
            )
            last = persist_eyes_messages(
                [{"role": "system", "content": rec, "surface": "cloud-glm"}],
                node_id="smoke_node",
                db_path=db,
            )
            self.assertGreater(last, 0)
            conn = sqlite3.connect(db)
            rows = conn.execute("SELECT role, content FROM messages").fetchall()
            conn.close()
            self.assertEqual(rows[0][0], "system")
            self.assertIn(EYES_PREFIX, rows[0][1])
            self.assertIn("可见数字 0", rows[0][1])


class M3DescribeTests(unittest.IsolatedAsyncioTestCase):
    async def test_describe_image_m3_prefixes_and_no_pixels_in_hop(self):
        from code_task.m3_vl_eyes import describe_image_m3

        fake = MagicMock()
        fake.raise_for_status = MagicMock()
        fake.json.return_value = {"message": {"content": "蜡烛图 三根红柱 OI 看不清"}, "model": "minimax-m3:cloud"}

        async_cm = MagicMock()
        async_cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=fake)))
        async_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("code_task.m3_vl_eyes.httpx.AsyncClient", return_value=async_cm):
            text, hop, ref = await describe_image_m3(
                {"mime": "image/jpeg", "base64": "abc123"},
                config={"minimax_m3_cloud_model": "minimax-m3:cloud"},
                route_id="r1",
                name="chart.jpg",
            )
        self.assertTrue(text.startswith(VL_PREFIX))
        self.assertIn("红柱", text)
        self.assertTrue(hop["vl_ok"])
        self.assertNotIn("abc123", str(hop))
        self.assertEqual(ref["name"], "chart.jpg")


if __name__ == "__main__":
    unittest.main()
