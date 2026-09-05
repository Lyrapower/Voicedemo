"""grid_store 面表 ⊆ grid_mem.SURFACE_NODE — 漏登记会让 b11 Cloud POST /messages 变 500。"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grid_mem import SURFACE_NODE, node_of, soul_of  # noqa: E402


def _store_fallback_surfaces():
    src = (ROOT / "grid-sovereign-runtime" / "gateway" / "grid_store.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id == "_NODE_SURFACE_FALLBACK":
                return set(ast.literal_eval(node.value).values())
    raise AssertionError("_NODE_SURFACE_FALLBACK not found")


class TestGridMemSurfaces(unittest.TestCase):
    def test_store_fallback_surfaces_are_registered(self):
        missing = sorted(s for s in _store_fallback_surfaces() if s not in SURFACE_NODE)
        self.assertEqual(
            missing,
            [],
            f"grid_mem.SURFACE_NODE 漏面(b11 Cloud 会 store HTTP 500): {missing}",
        )

    def test_b11_cloud_new_lanes_roundtrip(self):
        for surf, node in (
            ("cloud-kimi-k3", "cloud-kimi-k3"),
            ("cloud-glm53", "cloud-glm53"),
            ("cloud-glm53-full", "cloud-glm53-full"),
            ("cloud-minimax", "cloud-minimax"),
            ("cloud-deepseek", "cloud-deepseek"),
            ("cloud-glm", "cloud-glm52"),
            ("cloud-kimi", "cloud-kimi"),
            ("b11-expanded", "workbench-b11"),
        ):
            self.assertEqual(node_of(surf), node)
            self.assertEqual(soul_of(surf), "local" if surf.startswith("b11-") else "cloud")


if __name__ == "__main__":
    unittest.main()
