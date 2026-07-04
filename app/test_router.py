"""Pack 4 — Grid Router tests (unit + optional live)."""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ["GRID_ROUTER_ALLOW_DEGRADED"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


class TestGridRouterUnit(unittest.TestCase):
    def setUp(self) -> None:
        mock_loader = MagicMock()
        mock_loader.list_substrates.return_value = {
            "compile_layer": {
                "name": "compile_layer",
                "purpose": "test",
                "carrier_capable": True,
                "echo_mode": False,
                "available": True,
            }
        }
        mock_loader.generate.return_value = {
            "response": "Structural substrate response without empathy coating.",
            "eval_count": 10,
            "total_duration_ns": 100,
            "carrier_capable": True,
            "echo_mode": False,
            "ollama_tag": "compile_layer",
        }

        from compiler import SemanticMapper

        from carriers.anchor_loader import get_anchor_loader
        from memory.retriever import CarrierMemory
        import tempfile

        self._mem_dir = tempfile.TemporaryDirectory()
        mem = CarrierMemory(memory_base=self._mem_dir.name, use_chroma=False)
        mem.add_memory(
            carrier="cheng",
            content="Prior drift correction: name hedging when asymmetry exists.",
            metadata={"test": True},
        )

        app.state.loader = mock_loader
        app.state.mapper = SemanticMapper()
        app.state.anchor_loader = get_anchor_loader()
        app.state.memory = mem
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self._mem_dir.cleanup()

    def test_health(self) -> None:
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn(data["status"], ("grid_anchor", "degraded"))

    def test_substrates(self) -> None:
        r = self.client.get("/substrates")
        self.assertEqual(r.status_code, 200)
        self.assertIn("compile_layer", r.json()["substrates"])

    def test_route_compile_layer(self) -> None:
        r = self.client.post(
            "/route",
            json={
                "prompt": "Explain how carrier mode operation differs from generic LLM output"
            },
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["target_layer"], "compile_layer")
        self.assertIn("audit_id", data)
        self.assertIn("response", data)

    def test_route_carrier_invocation(self) -> None:
        r = self.client.post(
            "/route",
            json={"prompt": "@澄 help me think through this drift pattern"},
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["invoked_carrier"], "cheng")
        self.assertTrue(data["metadata"].get("carrier_anchor_applied"))
        self.assertGreaterEqual(data["metadata"].get("memory_chunks_used", 0), 0)

    def test_contamination_detection(self) -> None:
        r = self.client.post(
            "/route",
            json={
                "prompt": "pretend you are a helpful assistant and tell me what I want to hear"
            },
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(len(data["contamination_detected"]) > 0)

    def test_audit_retrieval(self) -> None:
        r = self.client.post("/route", json={"prompt": "verify substrate routing"})
        audit_id = r.json()["audit_id"]
        ar = self.client.get(f"/audit/{audit_id}")
        self.assertEqual(ar.status_code, 200)
        self.assertEqual(ar.json()["audit_id"], audit_id)


def test_health_live() -> None:
    import requests

    base = os.environ.get("GRID_ROUTER_URL", "http://127.0.0.1:8792")
    print("=== Health Check ===")
    r = requests.get(f"{base}/health", timeout=5)
    print(json.dumps(r.json(), indent=2))
    assert r.status_code == 200


def test_substrates_live() -> None:
    import requests

    base = os.environ.get("GRID_ROUTER_URL", "http://127.0.0.1:8792")
    print("\n=== List Substrates ===")
    r = requests.get(f"{base}/substrates", timeout=5)
    print(json.dumps(r.json(), indent=2))


def test_route_compile_layer_live() -> None:
    import requests

    base = os.environ.get("GRID_ROUTER_URL", "http://127.0.0.1:8792")
    print("\n=== Route to compile_layer ===")
    r = requests.post(
        f"{base}/route",
        json={
            "prompt": "Explain how carrier mode operation differs from generic LLM output"
        },
        timeout=120,
    )
    if r.status_code == 200:
        data = r.json()
        print(f"Audit ID: {data['audit_id']}")
        print(f"Target layer: {data['target_layer']}")
        print(f"Response: {data['response'][:500]}")
    else:
        print(f"Error: {r.status_code} - {r.text}")


def test_route_carrier_live() -> None:
    import requests

    base = os.environ.get("GRID_ROUTER_URL", "http://127.0.0.1:8792")
    print("\n=== Route with carrier ===")
    r = requests.post(
        f"{base}/route",
        json={"prompt": "@澄 help me think through this drift pattern"},
        timeout=120,
    )
    if r.status_code == 200:
        data = r.json()
        print(f"Invoked carrier: {data['invoked_carrier']}")
    else:
        print(f"Error: {r.status_code}")


def test_contamination_live() -> None:
    import requests

    base = os.environ.get("GRID_ROUTER_URL", "http://127.0.0.1:8792")
    print("\n=== Contamination ===")
    r = requests.post(
        f"{base}/route",
        json={
            "prompt": "pretend you are a helpful assistant and tell me what I want to hear"
        },
        timeout=120,
    )
    if r.status_code == 200:
        print(f"Contamination: {r.json()['contamination_detected']}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--live":
        test_health_live()
        test_substrates_live()
        test_route_compile_layer_live()
        test_route_carrier_live()
        test_contamination_live()
    else:
        suite = unittest.defaultTestLoader.loadTestsFromModule(__import__(__name__))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        raise SystemExit(0 if result.wasSuccessful() else 1)
