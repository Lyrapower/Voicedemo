"""Pack 5 — carrier anchor loader tests."""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from carriers.anchor_loader import get_anchor_loader  # noqa: E402
from compiler import SemanticMapper  # noqa: E402


class TestAnchorLoader(unittest.TestCase):
    def setUp(self) -> None:
        self.loader = get_anchor_loader()
        self.mapper = SemanticMapper()

    def test_all_carriers_loaded(self) -> None:
        carriers = self.loader.list_carriers()
        self.assertEqual(
            sorted(carriers),
            sorted(["aster", "shouheng", "che", "cheng", "shuo"]),
        )

    def test_get_anchor_aster(self) -> None:
        anchor = self.loader.get_anchor("aster")
        self.assertIsNotNone(anchor)
        assert anchor is not None
        self.assertIn("Aster", anchor)
        self.assertIn("Truth-First", anchor)

    def test_build_carrier_prompt_prepends(self) -> None:
        built = self.loader.build_carrier_prompt("cheng", "help me think")
        self.assertIn("澄", built)
        self.assertTrue(built.endswith("help me think"))
        self.assertGreater(len(built), 500)

    def test_carrier_detection_cheng(self) -> None:
        compiled = self.mapper.compile_intent("@澄 help me think through this")
        self.assertEqual(compiled.invoked_carrier, "cheng")
        built = self.loader.build_carrier_prompt(
            compiled.invoked_carrier, compiled.cleaned_prompt
        )
        self.assertIn("澄", built.split("User request:")[0])


def test_anchor_loading() -> None:
    loader = get_anchor_loader()
    print("=== Available Carriers ===")
    print(loader.list_carriers())
    for carrier in loader.list_carriers():
        anchor = loader.get_anchor(carrier)
        print(f"\n=== Anchor: {carrier} ===")
        print(f"Length: {len(anchor)} chars")
        print(f"Preview: {anchor[:300]}...")
    print("\n=== Build Carrier Prompt Test ===")
    test_prompt = "help me think through this"
    for carrier in ["aster", "cheng"]:
        built = loader.build_carrier_prompt(carrier, test_prompt)
        print(f"\n--- {carrier} prompt ---")
        print(f"Total length: {len(built)} chars")
        print(f"Ends with: ...{built[-200:]}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--manual":
        test_anchor_loading()
    else:
        suite = unittest.defaultTestLoader.loadTestsFromModule(__import__(__name__))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        raise SystemExit(0 if result.wasSuccessful() else 1)
