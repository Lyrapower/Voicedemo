"""Regression: b11 workbench UI (:8515) must default gateway API to :8501, never :8515/v1."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

B11 = Path(__file__).resolve().parent / "static" / "grid_workbench_b11.html"


class B11GatewayDefaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = B11.read_text(encoding="utf-8")

    def test_workbench_ui_port_constant(self) -> None:
        self.assertIn('WORKBENCH_UI_PORTS=new Set(["8515"])', self.src)

    def test_gateway_api_origin_pins_8501_on_workbench(self) -> None:
        self.assertIn("function gatewayApiOrigin()", self.src)
        self.assertIn("GATEWAY_API_PORT", self.src)
        self.assertRegex(
            self.src,
            r"if\(WORKBENCH_UI_PORTS\.has\(port\)\)[\s\S]{0,200}GATEWAY_API_PORT",
        )

    def test_default_gw_does_not_blindly_use_location_origin(self) -> None:
        block = re.search(r"function defaultGw\(\)\{[^}]+\}", self.src)
        self.assertIsNotNone(block)
        assert block is not None
        self.assertNotIn("location.origin", block.group(0))

    def test_migrate_bad_gateway_storage(self) -> None:
        self.assertIn("function migrateBadGatewayStorage()", self.src)
        self.assertIn('migrateBadGatewayStorage()', self.src)

    def test_reject_invalid_gateway_message(self) -> None:
        self.assertIn("8515 不提供 /v1", self.src)

    def test_no_silent_ollama_fallback_in_home_chat(self) -> None:
        block = re.search(r"async function homeChat\([\s\S]*?\n\}", self.src)
        self.assertIsNotNone(block)
        assert block is not None
        self.assertNotIn("/api/chat", block.group(0))
        self.assertIn("8501 gateway 不可用", block.group(0))

    def test_resolve_endpoint_rejects_workbench_port(self) -> None:
        self.assertRegex(
            self.src,
            r"function resolveEndpoint[\s\S]{0,400}WORKBENCH_UI_PORTS\.has\(u\.port\)",
        )

    def test_fetch_json_error_handlers_parseable(self) -> None:
        """Regression: orphaned brace in fetchJsonWithTimeout kills entire b11 UI."""
        m = re.search(r"async function fetchJsonWithTimeout[\s\S]*?\n\}", self.src)
        self.assertIsNotNone(m, "fetchJsonWithTimeout missing")
        block = m.group(0)
        self.assertIn("if(r.status===403){", block)
        self.assertIn("if(r.status===500){", block)
        self.assertIn("if(r.status===502||r.status===504){", block)
        self.assertEqual(block.count("{"), block.count("}"), block[:200])

    def test_pull_store_history_renders_after_refresh(self) -> None:
        self.assertIn("if(sendInFlight&&history.length>histLenAtStart) return", self.src)
        self.assertIn("if(!sendInFlight) renderHistory()", self.src)

    def test_critical_shell_script_present(self) -> None:
        """Separate shell script keeps tabs/store alive if main script parse fails."""
        self.assertIn('id="b11-shell"', self.src)
        self.assertIn("function b11CriticalShell()", self.src)
        self.assertIn("window.__b11Shell", self.src)
        self.assertIn("shellPullStore", self.src)

    def test_cloud_uses_own_active_window_not_studio(self) -> None:
        self.assertIn("function cloudActiveWindow(", self.src)
        self.assertIn("CLOUD_UI_TURNS=15", self.src)
        self.assertIn("function fetchCloudStoreAll(", self.src)
        self.assertIn("function buildCloudStoreMessages(", self.src)
        self.assertIn("buildCloudStoreMessages(mem,currentUser)", self.src)
        self.assertNotIn("客户端只送当前 user", self.src)
        self.assertIn("CLOUD_TOKEN_BUDGET=10000", self.src)
        self.assertIn("function isWorkLog(", self.src)
        self.assertIn('WORK_LOG_PREFIX="[工作日志]"', self.src)
        self.assertIn("工作日志·最近5条", self.src)
        self.assertIn("function cloudDualTrimPairs(", self.src)
        self.assertIn("signal_patterns.json", self.src)
        self.assertNotIn("iron-law-violation", self.src)
        self.assertIn("classify_v2", self.src)
        self.assertIn("execution_authority", self.src)
        self.assertIn("async function ensureCloudShared(", self.src)
        self.assertIn("function cloudChatUrl(", self.src)
        self.assertIn("/task/cloud_chat", self.src)
        self.assertIn('source:"aether_b11"', self.src)
        self.assertIn("mission_ref", self.src)
        self.assertIn("cloudStoreCache", self.src)
        self.assertIn("storeNode:\"cloud-glm52\"", self.src)
        self.assertIn("storeNode:\"cloud-glm53-full\"", self.src)
        self.assertIn('data-cloud="glm53_full"', self.src)
        self.assertIn(">GLM 5.3</button>", self.src)
        self.assertNotIn('data-cloud="minimax"', self.src)
        self.assertNotIn("MiniMax M3", self.src)
        self.assertIn("GLM经M3眼睛", self.src)
        self.assertIn("function isEyesProvenance(", self.src)
        self.assertIn("[眼睛·provenance]", self.src)
        self.assertNotIn("function cloudMemoryUrl(", self.src)
        self.assertIn("function rejectCloud8515Memory(", self.src)
        self.assertIn("function cloud8501Base(", self.src)
        self.assertNotIn("8515/cloud/chat", self.src)
        self.assertIn('STORE_CHAT_NODE="workbench-b11"', self.src)
        self.assertNotRegex(
            self.src,
            r"cloudHistories\[lane\]=activeWindow\(",
        )


if __name__ == "__main__":
    unittest.main()
