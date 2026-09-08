"""GRID_STORE_TOKEN is optional. A token file must not enable store auth."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

GATEWAY_DIR = Path(__file__).resolve().parents[1] / "gateway"
if str(GATEWAY_DIR.parent) not in sys.path:
    sys.path.insert(0, str(GATEWAY_DIR.parent))
if str(GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(GATEWAY_DIR))


class OptionalStoreTokenTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("GRID_STORE_TOKEN", None)
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "t.db")
        self.token_file = Path(self.tmp.name) / "grid_store.token"
        self.token_file.write_text("file-must-not-enable-auth\n", encoding="utf-8")

    def tearDown(self):
        os.environ.pop("GRID_STORE_TOKEN", None)
        self.tmp.cleanup()

    def test_file_without_env_allows_read_and_write(self):
        import grid_store as gs

        gs._TOKEN_FILE = self.token_file
        self.assertEqual(gs.live_store_token(), "")
        self.assertEqual(gs.store_auth_status(), "off")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(gs.build_router(self.db))
        c = TestClient(app)
        r = c.get("/store/conversations/smoke_node")
        self.assertEqual(r.status_code, 200)

    def test_env_set_still_401_without_header(self):
        os.environ["GRID_STORE_TOKEN"] = "test-only-not-production"
        import grid_store as gs
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(gs.build_router(self.db))
        c = TestClient(app)
        r = c.get("/store/conversations/smoke_node")
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
