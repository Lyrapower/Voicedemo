"""P0 static guards — Grid chain integrity (gateway / localStorage / fallback / FINAL).

Run: python3 -m unittest grid-sovereign-runtime/tests/test_grid_chain_integrity_static.py
Or via scripts/verify_grid_chain_integrity.sh
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
B11 = ROOT / "grid-sovereign-runtime" / "workbench" / "static" / "grid_workbench_b11.html"
GRID = ROOT / "grid-sovereign-runtime" / "gateway" / "static" / "grid.html"
MM = ROOT / "grid-sovereign-runtime" / "gateway" / "static" / "grid_multimodal.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class GridChainIntegrityStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.b11 = _read(B11)
        cls.grid = _read(GRID)
        cls.mm = _read(MM)

    # ── b11 gateway lock ──────────────────────────────────────────────

    def test_b11_gateway_api_origin_pins_8501(self) -> None:
        self.assertIn("function gatewayApiOrigin()", self.b11)
        self.assertIn('WORKBENCH_UI_PORTS=new Set(["8515"])', self.b11)
        block = re.search(r"function defaultGw\(\)\{[^}]+\}", self.b11)
        self.assertIsNotNone(block)
        assert block is not None
        self.assertNotIn("location.origin", block.group(0))

    def test_b11_no_silent_ollama_in_home_chat(self) -> None:
        block = re.search(r"async function homeChat\([\s\S]*?\n\}", self.b11)
        self.assertIsNotNone(block)
        assert block is not None
        self.assertNotIn("/api/chat", block.group(0))
        self.assertIn("8501 gateway 不可用", block.group(0))

    def test_b11_rejects_8515_v1_gateway(self) -> None:
        self.assertIn("8515 不提供 /v1", self.b11)
        self.assertIn("function migrateBadGatewayStorage()", self.b11)

    def test_b11_home_failure_uses_err_card_not_final(self) -> None:
        """HOME 已迁 EXPANDED;homeChat 失败抛错,send 失败路径用 card err 非 finalCard。"""
        self.assertIn('if(mode==="home") mode="expanded"', self.b11)
        home = re.search(r"async function homeChat\([\s\S]*?\n\}", self.b11)
        self.assertIsNotNone(home)
        assert home is not None
        self.assertIn("8501 gateway 不可用", home.group(0))
        self.assertNotIn("finalCard(", home.group(0))
        # send() expanded catch → card err
        self.assertIn('class="card err"', self.b11)
        send = re.search(r"async function send\(\)\{[\s\S]*?\n\}", self.b11)
        self.assertIsNotNone(send)
        assert send is not None
        self.assertIn("card err", send.group(0))
        # failure catch must not call finalCard
        catch_blocks = re.findall(r"catch\(e\)\{[\s\S]{0,500}\}", send.group(0))
        for block in catch_blocks:
            self.assertNotIn("finalCard(", block)

    def test_b11_expanded_failure_uses_err_card_not_final(self) -> None:
        # expanded 主路径在 send(): catch → card err
        block = re.search(
            r'if\(mode==="expanded"\|\|mode==="expanded_glm53"\)\{[\s\S]*?else if\(mode==="shadow"\)',
            self.b11,
        )
        self.assertIsNotNone(block)
        assert block is not None
        self.assertIn('class="card err"', block.group(0))
        self.assertNotIn("finalCard(card)", block.group(0).split("catch(e)")[-1][:400])

    def test_b11_expanded_interim_not_on_workbench_port(self) -> None:
        block = re.search(r"async function expandedOrchestrate\([\s\S]*?\n\}", self.b11)
        self.assertIsNotNone(block)
        assert block is not None
        self.assertIn("WORKBENCH_UI_PORTS.has", block.group(0))

    # ── grid.html routing guards ────────────────────────────────────────

    def test_grid_resolve_gw_ts_net_uses_default(self) -> None:
        block = re.search(r"function resolveGw\(\)\{[\s\S]*?\n\}", self.grid)
        self.assertIsNotNone(block)
        assert block is not None
        self.assertIn('.endsWith(".ts.net")', block.group(0))

    def test_grid_resolve_gw_blocks_localhost_from_remote(self) -> None:
        block = re.search(r"function resolveGw\(\)\{[\s\S]*?\n\}", self.grid)
        self.assertIsNotNone(block)
        assert block is not None
        self.assertIn("isLocalHost(u.hostname)", block.group(0))
        self.assertIn("!isLocalHost(location.hostname)", block.group(0))

    def test_grid_no_direct_ollama_chat_fallback_in_send(self) -> None:
        send = re.search(r"async function send\([\s\S]*?\n\}", self.grid)
        self.assertIsNotNone(send)
        assert send is not None
        self.assertNotIn("/api/chat", send.group(0))
        self.assertNotIn(":11434", send.group(0))

    def test_grid_multimodal_defaults_8501_not_origin_only(self) -> None:
        self.assertIn(":8501", self.mm)
        block = re.search(r"function hostBase\(\)[\s\S]{0,200}", self.mm)
        self.assertIsNotNone(block)

    # ── shared forbidden patterns ───────────────────────────────────────

    def test_no_workbench_port_in_default_chat_url_helper(self) -> None:
        for name, src in (("b11", self.b11), ("grid_multimodal", self.mm)):
            if "8515/v1" in src.replace("8515 不提供 /v1", ""):
                self.fail(f"{name}: literal 8515/v1 gateway URL found")

    def test_b11_storage_keys_prefixed(self) -> None:
        self.assertIn('"b11_"+k', self.b11)


if __name__ == "__main__":
    unittest.main()
