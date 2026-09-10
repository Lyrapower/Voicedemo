"""PKG_PRESTART_v1 step 2 — CC_SANDBOX_TIMEOUT_S from env/config, not a literal at the sweep."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness_resident"))

from harness.cc_sandbox_timeout import DEFAULT_CC_SANDBOX_TIMEOUT_S, sandbox_timeout_s  # noqa: E402


class TestSandboxTimeout(unittest.TestCase):
    def test_default_is_measured_363(self):
        os.environ.pop("CC_SANDBOX_TIMEOUT_S", None)
        self.assertEqual(sandbox_timeout_s(None), 363)
        self.assertEqual(DEFAULT_CC_SANDBOX_TIMEOUT_S, 363)
        self.assertGreaterEqual(DEFAULT_CC_SANDBOX_TIMEOUT_S, 300)

    def test_env_overrides_config(self):
        os.environ["CC_SANDBOX_TIMEOUT_S"] = "400"
        try:
            cfg = SimpleNamespace(cc=SimpleNamespace(sandbox_timeout_s=363))
            self.assertEqual(sandbox_timeout_s(cfg), 400)
        finally:
            os.environ.pop("CC_SANDBOX_TIMEOUT_S", None)

    def test_config_when_env_absent(self):
        os.environ.pop("CC_SANDBOX_TIMEOUT_S", None)
        cfg = SimpleNamespace(cc=SimpleNamespace(sandbox_timeout_s=500))
        self.assertEqual(sandbox_timeout_s(cfg), 500)
