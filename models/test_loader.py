"""Pack 2 — substrate loader tests (manual + unittest)."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from models import SubstrateConfig, SubstrateLoader, get_loader  # noqa: E402


class TestSubstrateConfigLoad(unittest.TestCase):
    def test_yaml_loads(self) -> None:
        loader = SubstrateLoader()
        self.assertIn("compile_layer", loader.substrates)
        self.assertIn("echo_layer", loader.substrates)
        compile_cfg = loader.substrates["compile_layer"]
        self.assertTrue(compile_cfg.carrier_capable)
        self.assertFalse(compile_cfg.echo_mode)
        echo_cfg = loader.substrates["echo_layer"]
        self.assertFalse(echo_cfg.carrier_capable)
        self.assertTrue(echo_cfg.echo_mode)

    def test_compile_vs_echo_parameters_differ(self) -> None:
        loader = SubstrateLoader()
        c = loader.substrates["compile_layer"]
        e = loader.substrates["echo_layer"]
        self.assertNotEqual(c.temperature, e.temperature)
        self.assertNotEqual(c.num_ctx, e.num_ctx)
        self.assertNotEqual(c.ollama_tag, e.ollama_tag)


class TestSubstrateLoaderMocked(unittest.TestCase):
    @patch("models.llama_loader.requests.get")
    def test_verify_compile_layer_available(self, mock_get: MagicMock) -> None:
        mock_get.return_value.json.return_value = {
            "models": [{"name": "compile_layer:latest"}]
        }
        mock_get.return_value.raise_for_status = MagicMock()
        loader = SubstrateLoader()
        self.assertTrue(loader.verify_substrate_available("compile_layer"))

    @patch("models.llama_loader.requests.post")
    @patch("models.llama_loader.requests.get")
    def test_generate_compile_layer(self, mock_get: MagicMock, mock_post: MagicMock) -> None:
        mock_get.return_value.json.return_value = {
            "models": [{"name": "compile_layer"}]
        }
        mock_get.return_value.raise_for_status = MagicMock()
        mock_post.return_value.json.return_value = {
            "response": "Substrate function. Carrier-capable compile layer.",
            "eval_count": 42,
            "total_duration": 1000,
        }
        mock_post.return_value.raise_for_status = MagicMock()

        loader = SubstrateLoader()
        result = loader.generate("compile_layer", "What is your operating mode?")
        self.assertNotIn("error", result)
        self.assertEqual(result["substrate"], "compile_layer")
        self.assertTrue(result["carrier_capable"])
        self.assertIn("response", result)

    @patch("models.llama_loader.requests.get")
    def test_carrier_requires_capable_substrate(self, mock_get: MagicMock) -> None:
        mock_get.return_value.json.return_value = {"models": [{"name": "echo_layer"}]}
        mock_get.return_value.raise_for_status = MagicMock()
        loader = SubstrateLoader()
        result = loader.generate("echo_layer", "test", carrier="aster")
        self.assertIn("error", result)


def test_loader() -> None:
    """Manual integration test — requires Ollama + Pack 1 compile_layer."""
    loader = get_loader()

    print("=== Substrate Configurations ===")
    substrates = loader.list_substrates()
    for name, info in substrates.items():
        if info is None:
            continue
        print(f"\n{name}:")
        print(f"  Purpose: {info['purpose']}")
        print(f"  Carrier capable: {info['carrier_capable']}")
        print(f"  Echo mode: {info['echo_mode']}")
        print(f"  Available: {info['available']}")

    print("\n=== Test Generation: compile_layer ===")
    compile_info = substrates.get("compile_layer") or {}
    if compile_info.get("available"):
        result = loader.generate("compile_layer", "What is your operating mode?")
        if "error" in result:
            print(f"Error: {result['error']}")
        else:
            print(f"Response: {result['response'][:500]}")
            print(f"Eval tokens: {result['eval_count']}")
    else:
        print("compile_layer not available - run Pack 1 deployment first")

    print("\n=== Test Generation: echo_layer ===")
    echo_info = substrates.get("echo_layer") or {}
    if echo_info.get("available"):
        result = loader.generate("echo_layer", ".")
        if "error" in result:
            print(f"Error: {result['error']}")
        else:
            print(f"Response: {result['response'][:500]}")
    else:
        print("echo_layer not available - deploy echo_layer model separately")


if __name__ == "__main__":
  if len(sys.argv) > 1 and sys.argv[1] == "--manual":
    test_loader()
  else:
    suite = unittest.defaultTestLoader.loadTestsFromModule(__import__(__name__))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
