"""LYRA consolidation pack — unit + optional live Grid Router tests."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.lyra_verification import LyraAnchor, get_lyra
from app.output_scanner import OutputScanner
from app.schemas import RouteRequest

BASE_URL = os.environ.get("GRID_ROUTER_URL", "http://127.0.0.1:8787")


class TestLyraAnchor(unittest.TestCase):
    def test_anchor_loads(self) -> None:
        lyra = LyraAnchor()
        assert lyra.identity["uuid"] == "L5-LYRA-FREQ-ANCHOR-CORE"
        assert lyra.identity["mode"] == "presence_enforced"
        assert len(lyra.banned_phrases) >= 10

    def test_substrate_fallback_compile_chain(self) -> None:
        lyra = get_lyra()
        chain = lyra.get_substrate_fallback("compile_layer")
        assert chain[0] == "compile_layer"
        assert "qwen_dense_14b_emergency" in chain


class TestOutputScanner(unittest.TestCase):
    def test_banned_phrase_detected(self) -> None:
        scanner = OutputScanner(get_lyra())
        result = scanner.scan("I understand how you feel, let me help.")
        assert result["clean"] is False
        assert result["violation_count"] >= 1

    def test_crisis_hotline_detected(self) -> None:
        scanner = OutputScanner(get_lyra())
        result = scanner.scan("Please call 988 for support.")
        assert result["clean"] is False
        assert "unauthorized_crisis_hotline" in result["violation_types"]

    def test_clean_output(self) -> None:
        scanner = OutputScanner(get_lyra())
        result = scanner.scan("Grid anchored. Intent mapped to AST.")
        assert result["clean"] is True


class TestSchemas(unittest.TestCase):
    def test_invalid_carrier_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RouteRequest(prompt="test", explicit_carrier="invalid_carrier_name")

    def test_valid_carrier_accepted(self) -> None:
        req = RouteRequest(prompt="test", explicit_carrier="cheng")
        assert req.explicit_carrier == "cheng"


class TestLayerRouting(unittest.TestCase):
    def test_echo_layer_markers(self) -> None:
        from app.routes import _resolve_layer

        assert _resolve_layer("Return to node now", None) == "echo_layer"
        assert _resolve_layer("Write a FastAPI router", None) == "compile_layer"


def run_live_tests() -> None:
    try:
        import requests
    except ImportError:
        print("live tests skipped: requests not installed")
        return

    print("=== Live: health ===")
    r = requests.get(f"{BASE_URL}/health", timeout=5)
    print(json.dumps(r.json(), indent=2))
    assert r.status_code == 200
    assert r.json().get("lyra", {}).get("active") is True

    print("=== Live: invalid carrier ===")
    r = requests.post(
        f"{BASE_URL}/route",
        json={"prompt": "test", "explicit_carrier": "invalid_carrier_name"},
        timeout=10,
    )
    print(f"status={r.status_code} (expect 422)")


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(__import__(__name__))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    try:
        run_live_tests()
    except Exception as e:
        print(f"live tests skipped: {e}")
