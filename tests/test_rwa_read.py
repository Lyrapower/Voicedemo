"""PKG_PRESTART_v1 step 3 — rwa.read + G1/G3."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "harness_resident"))


class _Rpc(BaseHTTPRequestHandler):
    block = "0x10"
    chain_id = "0x1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        method = body.get("method")
        if method == "eth_blockNumber":
            result = type(self).block
        elif method == "eth_chainId":
            result = type(self).chain_id
        else:
            result = "0x0"
        raw = json.dumps({"jsonrpc": "2.0", "id": body.get("id", 1), "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _serve(block: str) -> tuple[ThreadingHTTPServer, str]:
    class H(_Rpc):
        pass
    H.block = block
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


class TestRwaRead(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.tmp.name, "prov.jsonl")
        os.environ["HARNESS_PROVENANCE_LOG"] = self.log
        from app.harness import provenance
        provenance._RECORDING = False

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("HARNESS_PROVENANCE_LOG", None)

    def test_buidl_skipped_no_address(self):
        from harness.rwa_read import execute
        out = execute(symbol="BUIDL", chain="ethereum", rpc_env={})
        self.assertEqual(len(out["cards"]), 1)
        c = out["cards"][0]
        self.assertEqual(c["skip"], "no_address")
        self.assertEqual(c["confidence"], "skipped")
        self.assertIsNone(c.get("total_supply"))

    def test_g3_reject_upgrade_on_older_block_then_accept_newer(self):
        from harness.rwa_read import _emit, _g3_guard

        a = {"symbol": "USYC", "chain": "ethereum", "confidence": "witnesses_agree",
             "source_url": "https://example.test", "block": 100, "evidence_grade": "witnesses_agree"}
        _emit(a)
        older = dict(a, confidence="attested", evidence_grade="attested", block=99)
        self.assertEqual(_g3_guard(older), "rejected:confidence_upgrade_without_newer_block")
        _emit(older, status="DENIED", error="rejected:confidence_upgrade_without_newer_block")
        newer = dict(a, confidence="attested", evidence_grade="attested", block=101)
        self.assertIsNone(_g3_guard(newer))
        ev = _emit(newer)
        self.assertEqual(ev.get("status"), "EXECUTED")

    def test_rpc2_wrong_height_is_dispute_no_numbers(self):
        from harness.rwa_read import execute
        s1, u1 = _serve("0x100")
        s2, u2 = _serve("0x50")
        try:
            reg = [{
                "symbol": "USYC", "issuer": "Circle", "chain": "ethereum", "chain_id": 1,
                "address": "0x136471a34f6ef19fE571EFFC1CA711fdb8E49f2b",
                "source_url": "https://developers.circle.com/tokenized/usyc/smart-contracts",
            }]
            out = execute(symbol="USYC", chain="ethereum", registry=reg, rpc_env={1: (u1, u2, "required")})
        finally:
            s1.shutdown(); s2.shutdown()
        c = out["cards"][0]
        self.assertEqual(c["confidence"], "dispute")
        self.assertIsNone(c.get("total_supply"))
        self.assertIsNone(c.get("supply_units"))


if __name__ == "__main__":
    unittest.main()
