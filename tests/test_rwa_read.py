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
        out = execute(symbol="BUIDL", chain="ethereum", rpc_env={}, attach_xyz=False)
        self.assertEqual(len(out["cards"]), 1)
        c = out["cards"][0]
        self.assertEqual(c["skip"], "no_address")
        self.assertEqual(c["confidence"], "skipped")
        self.assertEqual(c.get("judgment"), "MISS")
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

    def test_g3_same_block_replay_and_hash(self):
        from harness.rwa_read import _emit, _g3_guard
        a = {"symbol": "USYC", "chain": "ethereum", "confidence": "witnesses_agree",
             "source_url": "https://example.test", "block": 100, "block_hash": "aaa",
             "evidence_grade": "witnesses_agree"}
        _emit(a)
        self.assertIsNone(_g3_guard(dict(a)))
        same_h = dict(a, confidence="attested", evidence_grade="attested")
        self.assertEqual(_g3_guard(same_h), "rejected:confidence_upgrade_without_newer_block")
        mismatch = dict(a, block_hash="bbb")
        self.assertEqual(_g3_guard(mismatch), "rejected:same_height_hash_mismatch")

    def test_g3_newer_block_needs_evidence(self):
        from harness.rwa_read import _emit, _g3_guard
        a = {"symbol": "USYC", "chain": "ethereum", "confidence": "witnesses_agree",
             "source_url": "https://example.test", "block": 100, "evidence_grade": "witnesses_agree"}
        _emit(a)
        bare = {"symbol": "USYC", "chain": "ethereum", "confidence": "attested",
                "block": 102, "evidence_grade": "attested"}
        self.assertEqual(_g3_guard(bare), "rejected:confidence_upgrade_without_evidence")

    def test_judgment_enum_map(self):
        from harness.rwa_read import judgment_for_card
        self.assertEqual(judgment_for_card("witnesses_agree"), "HIT")
        self.assertEqual(judgment_for_card("witnesses_agree", fresh=False), "BLOCKED")
        self.assertEqual(judgment_for_card("dispute"), "MISS")
        self.assertEqual(judgment_for_card("skipped"), "MISS")
        self.assertEqual(judgment_for_card("issuer_claim"), "UNKNOWN")
        self.assertEqual(judgment_for_card("not_a_grade"), "UNKNOWN")

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
            out = execute(symbol="USYC", chain="ethereum", registry=reg, rpc_env={1: (u1, u2, "required")}, attach_xyz=False)
        finally:
            s1.shutdown(); s2.shutdown()
        c = out["cards"][0]
        self.assertEqual(c["confidence"], "dispute")
        self.assertIsNone(c.get("total_supply"))
        self.assertIsNone(c.get("supply_units"))

    def test_parse_rwa_xyz_labeled_fields(self):
        from harness.rwa_read import parse_rwa_xyz_text
        text = "Total Asset Value\n$2.60B\nNet Asset Value\n$1.14\nHolders\n34\n"
        p = parse_rwa_xyz_text(text)
        self.assertEqual(p["status"], "ok")
        self.assertEqual(p["total_usd_all_chains"], 2.6e9)
        self.assertEqual(p["nav_usd"], 1.14)
        self.assertEqual(p["holders"], 34)
        empty = parse_rwa_xyz_text("Sign up for a free account")
        self.assertEqual(empty["status"], "empty")
        self.assertNotIn("total_usd_all_chains", empty)

    def test_xyz_column_not_copied_onto_supply(self):
        from harness.rwa_read import XYZ_COL, execute
        from unittest.mock import patch
        fake = {"source": "rwa.xyz", "grade": "secondhand", "status": "ok",
                "total_usd_all_chains": 2.6e9, "nav_usd": 1.14, "holders": 34}
        with patch("harness.rwa_read.fetch_rwa_xyz_reference", return_value=fake):
            out = execute(symbol="BUIDL", chain="ethereum", rpc_env={}, attach_xyz=True)
        c = out["cards"][0]
        self.assertEqual(c["skip"], "no_address")
        self.assertIsNone(c.get("total_supply"))
        self.assertIsNone(c.get("nav_usd"))
        self.assertEqual(c[XYZ_COL]["holders"], 34)
        self.assertEqual(c[XYZ_COL]["nav_usd"], 1.14)


if __name__ == "__main__":
    unittest.main()
