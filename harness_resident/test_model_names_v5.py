#!/usr/bin/env python3
"""§1: config model names match 8501 /v1/models; mismatch glm-5.9 is red."""
from __future__ import annotations
import asyncio, json, os, sys, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
os.chdir(HERE)


class ModelNameTests(unittest.TestCase):
    def test_config_four_cloud_routes(self):
        from harness.config import load_config
        from harness.gateway import MODEL_TO_SUBSTRATE
        cfg = load_config("config.toml")
        self.assertEqual(cfg.models.fast_route, "glm-5.3-flash")
        self.assertEqual(cfg.models.deep_route, "glm-5.2")
        self.assertEqual(cfg.models.full_route, "glm-5.3")
        self.assertEqual(cfg.models.research_route, "deepseek-v4-pro")
        self.assertEqual(MODEL_TO_SUBSTRATE[cfg.models.fast_route], "glm53")
        self.assertEqual(MODEL_TO_SUBSTRATE[cfg.models.deep_route], "glm52")
        self.assertEqual(MODEL_TO_SUBSTRATE[cfg.models.full_route], "glm53_full")
        self.assertEqual(MODEL_TO_SUBSTRATE[cfg.models.research_route], "deepseek_v4")

    def test_resolved_equals_config_four_routes(self):
        asyncio.run(self._four())

    async def _four(self):
        import httpx
        from harness.gateway import GatewayClient, MODEL_TO_SUBSTRATE

        def app(request: httpx.Request):
            if request.url.path != "/task/cloud_chat":
                return httpx.Response(404)
            body = json.loads(request.content)
            sub = body["substrate"]
            model = {v: k for k, v in MODEL_TO_SUBSTRATE.items()}[sub]
            return httpx.Response(200, json={"ok": True, "content": "pong", "model": model, "substrate": sub})

        class Core:
            gateway_base = "http://stub"
            gateway_timeout_seconds = 5.0
            max_tokens = 16

        class Cfg:
            core = Core()

        gc = GatewayClient(Cfg(), client=httpx.AsyncClient(base_url="http://stub", transport=httpx.MockTransport(app)))
        for name in ("glm-5.3-flash", "glm-5.2", "glm-5.3", "deepseek-v4-pro"):
            r = await gc.chat(name, [{"role": "user", "content": "x"}])
            self.assertEqual(r["model"], name, name)
        await gc.close()

    def test_glm59_mismatch_red(self):
        asyncio.run(self._bad())

    async def _bad(self):
        import httpx
        from harness.gateway import GatewayClient, ModelMismatch

        def app(request: httpx.Request):
            return httpx.Response(200, json={"ok": True, "content": "x", "model": "glm-5.2"})

        class Core:
            gateway_base = "http://stub"
            gateway_timeout_seconds = 5.0
            max_tokens = 16

        class Cfg:
            core = Core()

        gc = GatewayClient(Cfg(), client=httpx.AsyncClient(base_url="http://stub", transport=httpx.MockTransport(app)))
        with self.assertRaises(ModelMismatch):
            await gc.chat("glm-5.9", [{"role": "user", "content": "x"}])
        await gc.close()

    def test_cloud_suffix_matches_config_name(self):
        asyncio.run(self._suffix())

    async def _suffix(self):
        import httpx
        from harness.gateway import GatewayClient

        def app(request: httpx.Request):
            return httpx.Response(200, json={"ok": True, "content": "x", "model": "glm-5.2:cloud"})

        class Core:
            gateway_base = "http://stub"
            gateway_timeout_seconds = 5.0
            max_tokens = 16

        class Cfg:
            core = Core()

        gc = GatewayClient(Cfg(), client=httpx.AsyncClient(base_url="http://stub", transport=httpx.MockTransport(app)))
        r = await gc.chat("glm-5.2", [{"role": "user", "content": "x"}])
        self.assertEqual(r["model"], "glm-5.2:cloud")
        await gc.close()


if __name__ == "__main__":
    unittest.main()
