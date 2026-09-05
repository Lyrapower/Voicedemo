"""RWA CHAIN CONNECT v1 · T2–T6 isolated; T1 live only when authorized RPC env is set."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.harness.action_envelope import FactualReceipt
from app.harness import provenance
from app.crypto_rwa.rwa_chain_connect import (
    connect_run,
    grade_fact,
    load_published,
    read_with_receipt,
    vendor_of,
)


def _iso_env(td: str) -> dict[str, str]:
    return {
        "HARNESS_PROVENANCE_LOG": str(Path(td) / "prov.jsonl"),
        "RWA_CONNECT_STATE": td,
        "RWA_CONNECT_PUBLISHED": str(Path(td) / "published.json"),
        "RWA_CONNECT_LOCK": str(Path(td) / "lock"),
        "RWA_CONNECT_EVIDENCE": str(Path(td) / "ev"),
    }


ALC = "https://eth-mainnet.g.alchemy.com/v2/dummy"
QN = "https://demo.quiknode.pro/dummy"
ANKR = "https://rpc.ankr.com/bsc/dummy"

CTX = {"mission_id": "m-connect", "action_id": "seed", "decision_origin": "USER"}
USYC = {
    "symbol": "USYC", "issuer": "Circle", "chain": "ethereum", "chain_id": 1,
    "address": "0x136471a34f6ef19fE571EFFC1CA711fdb8E49f2b",
}
BUIDL = {
    "symbol": "BUIDL", "issuer": "BlackRock", "chain": "ethereum", "chain_id": 1, "address": None,
}


class GradeFactT2(unittest.TestCase):
    def test_dual_same_block_third_party_is_witnesses_agree_not_attested(self):
        g = grade_fact(
            confidence="dual", node_ownership="third_party", same_block=True,
            independent_upstreams=True, attested_proof=False,
        )
        self.assertEqual(g, "witnesses_agree")

    def test_dual_different_blocks_not_witnesses_agree(self):
        g = grade_fact(
            confidence="dual", node_ownership="third_party", same_block=False,
            independent_upstreams=True, attested_proof=False,
        )
        self.assertEqual(g, "unverified")

    def test_shared_upstream_not_witnesses_agree(self):
        g = grade_fact(
            confidence="dual", node_ownership="third_party", same_block=True,
            independent_upstreams=False, attested_proof=False, shared_upstream=True,
        )
        self.assertEqual(g, "witness_only")

    def test_single_is_witness_only(self):
        g = grade_fact(
            confidence="single", node_ownership="third_party", same_block=True,
            independent_upstreams=False, attested_proof=False,
        )
        self.assertEqual(g, "witness_only")

    def test_timeout_unverified(self):
        g = grade_fact(
            confidence="dual", node_ownership="third_party", same_block=True,
            independent_upstreams=True, attested_proof=False, timeout=True,
        )
        self.assertEqual(g, "unverified")

    def test_attested_only_self_hosted_with_proof(self):
        g = grade_fact(
            confidence="dual", node_ownership="self_hosted", same_block=True,
            independent_upstreams=True, attested_proof=True,
        )
        self.assertEqual(g, "attested")
        capped = grade_fact(
            confidence="dual", node_ownership="third_party", same_block=True,
            independent_upstreams=True, attested_proof=True,
        )
        self.assertEqual(capped, "witnesses_agree")

    def test_unauthorized_vendor_stops(self):
        with self.assertRaises(ValueError) as cm:
            vendor_of("https://evil.example/rpc")
        self.assertIn("authorized list", str(cm.exception))


class IsolatedConnectTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._old = {k: os.environ.get(k) for k in _iso_env(self._td.name)}
        os.environ.update(_iso_env(self._td.name))

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._td.cleanup()

    def test_t3_missing_address_no_invented_numbers(self):
        card_ok = {
            "symbol": "USYC", "chain": "ethereum", "confidence": "dual",
            "supply_units": 1.0, "total_supply": 10, "decimals": 6,
            "nav_usd": 1.13, "block": "0x1", "read_ts": "2026-09-05T00:00:00+00:00",
            "error": None,
        }
        ok = read_with_receipt(
            {**CTX, "action_id": "r1|USYC|ethereum"}, USYC, run_id="r1",
            card=card_ok, rpc_pair=(ALC, QN),
        )
        miss = read_with_receipt(
            {**CTX, "action_id": "r1|BUIDL|ethereum"}, BUIDL, run_id="r1",
            rpc_pair=(ALC, QN),
        )
        self.assertEqual(ok["status"], "EXECUTED")
        self.assertEqual(ok["factual_payload"]["supply_units"], 1.0)
        self.assertIsNotNone(ok["receipt_id"])
        self.assertIn("无地址", miss["factual_payload"]["error"])
        self.assertIsNone(miss["factual_payload"].get("supply_units"))
        self.assertIsNone(miss["factual_payload"].get("nav_usd"))
        self.assertIsNone(miss["factual_payload"].get("total_supply"))
        self.assertNotEqual(miss["status"], "EXECUTED")

    def test_t4_derived_attested_rejected_descent_and_independence(self):
        parent = {"evidence_grade": "secondhand", "receipt_id": "p1"}
        with self.assertRaises(ValueError) as cm:
            provenance.record_receipt(FactualReceipt(
                mission_id="m4", action_id="child", status="EXECUTED", executed=True,
                metadata={"evidence_grade": "attested", "derived_from": parent},
            ))
        self.assertIn("derived fact exceeds parent", str(cm.exception))
        provenance.record_receipt(FactualReceipt(
            mission_id="m4", action_id="child", status="EXECUTED", executed=True,
            metadata={"evidence_grade": "unverified", "derived_from": parent},
        ))
        provenance.record_receipt(FactualReceipt(
            mission_id="m4", action_id="other-asset", status="EXECUTED", executed=True,
            metadata={"evidence_grade": "witnesses_agree"},
        ))
        ev = provenance.read_events("m4")
        child = [e for e in ev if e.get("event_id") == "child"]
        other = [e for e in ev if e.get("event_id") == "other-asset"]
        self.assertEqual(len(child), 1)
        self.assertEqual(child[0]["evidence_grade"], "unverified")
        self.assertEqual(other[0]["evidence_grade"], "witnesses_agree")
        provenance.record_receipt(FactualReceipt(
            mission_id="m4", action_id="new-indep", status="EXECUTED", executed=True,
            metadata={"evidence_grade": "attested"},
        ))
        child_again = [e for e in provenance.read_events("m4") if e.get("event_id") == "child"]
        self.assertEqual(child_again[0]["evidence_grade"], "unverified")
        with self.assertRaises(ValueError):
            provenance.record_receipt(FactualReceipt(
                mission_id="m4", action_id="v", status="VERIFIED", executed=True, metadata={},
            ))

    def test_t5_retry_reuses_receipt_publish_fail_not_connected(self):
        card = {
            "symbol": "USYC", "chain": "ethereum", "confidence": "single",
            "supply_units": 2.0, "total_supply": 20, "decimals": 6,
            "block": "0x2", "read_ts": "2026-09-05T01:00:00+00:00", "error": None,
        }
        first = read_with_receipt(
            {**CTX, "action_id": "r5|USYC|ethereum"}, USYC, run_id="r5",
            card=card, rpc_pair=(ALC, None),
        )
        second = read_with_receipt(
            {**CTX, "action_id": "r5|USYC|ethereum"}, USYC, run_id="r5",
            card=card, rpc_pair=(ALC, None),
        )
        self.assertTrue(second.get("reused"))
        self.assertEqual(first["receipt_id"], second["receipt_id"])
        n = len([e for e in provenance.read_events("m-connect") if e.get("kind") == "receipt"
                 and e.get("event_id") == "r5|USYC|ethereum"])
        self.assertEqual(n, 1)

        fake_doc = {
            "cards": [card], "skipped": [], "summary": {},
            "read_ts": "2026-09-05T01:00:00+00:00",
        }
        with patch("app.crypto_rwa.rwa_chain_connect.R.run", return_value=fake_doc):
            pub = connect_run(
                CTX, run_id="r5-pub", registry=[USYC],
                rpc_env={1: (ALC, None, "optional")}, fail_publish=True,
            )
        self.assertFalse(pub["connected"])
        self.assertFalse(load_published().get("connected"))

        with patch("app.crypto_rwa.rwa_chain_connect.R.run", return_value=fake_doc):
            pub2 = connect_run(CTX, run_id="r5-ok", registry=[USYC], rpc_env={1: (ALC, None, "optional")})
        self.assertTrue(pub2["connected"])
        rid = pub2["receipts"][0]["receipt_id"]
        ids = []

        def _once():
            with patch("app.crypto_rwa.rwa_chain_connect.R.run", return_value=fake_doc):
                p = connect_run(CTX, run_id="r5-ok", registry=[USYC], rpc_env={1: (ALC, None, "optional")})
                ids.append(p["receipts"][0]["receipt_id"])

        t1 = threading.Thread(target=_once)
        t2 = threading.Thread(target=_once)
        t1.start(); t2.start(); t1.join(); t2.join()
        self.assertEqual(set(ids), {rid})

        with patch("app.crypto_rwa.rwa_chain_connect.read_with_receipt", side_effect=RuntimeError("boom")):
            with patch("app.crypto_rwa.rwa_chain_connect.R.run", return_value=fake_doc):
                bad = connect_run(CTX, run_id="r5-fail", registry=[USYC], rpc_env={1: (ALC, None, "optional")})
        self.assertFalse(bad["connected"])
        self.assertIsNone(bad["receipts"][0].get("receipt_id"))

    def test_t6_verify_chain_and_stale_cache(self):
        card = {
            "symbol": "USYC", "chain": "ethereum", "confidence": "single",
            "supply_units": 3.0, "total_supply": 30, "decimals": 6,
            "block": "0x3", "read_ts": "2026-09-04T12:00:00+00:00", "error": None,
        }
        with patch("app.crypto_rwa.rwa_chain_connect.R.run", return_value={
            "cards": [card], "skipped": [], "summary": {}, "read_ts": "2026-09-04T12:00:00+00:00",
        }):
            pub = connect_run(CTX, run_id="r6", registry=[USYC], rpc_env={1: (ALC, None, "optional")})
        self.assertTrue(pub["connected"])
        loaded = load_published()
        self.assertTrue(loaded["stale"])
        self.assertEqual(loaded["stale_label"], "last_success")
        ev = provenance.read_events("m-connect")
        self.assertTrue(provenance.verify_chain(ev))
        broken = list(ev)
        if broken:
            broken[0] = dict(broken[0], event_hash="deadbeefdeadbeef")
            self.assertFalse(provenance.verify_chain(broken))
        from app.platform_main import _load_onchain_live
        live = _load_onchain_live()
        self.assertEqual(live["receipts"][0]["receipt_id"], pub["receipts"][0]["receipt_id"])
        self.assertTrue(live.get("webpage_cards_are_reference") or live.get("stale"))


def _quiet_rpc_env() -> bool:
    for rel in (".env", "aether_nexus/.env"):
        p = ROOT / rel
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip("'").strip('"')
            if k in ("ETH_RPC_URL", "ETH_RPC_URL_2", "BSC_RPC_URL", "BSC_RPC_URL_2", "BSC_RPC_SECOND_POLICY"):
                os.environ.setdefault(k, v)
    return bool(os.environ.get("ETH_RPC_URL"))


@unittest.skipUnless(
    os.environ.get("RWA_T1_LIVE") == "1" and _quiet_rpc_env(),
    "T1 live only when RWA_T1_LIVE=1 and ETH_RPC_URL set (avoids mock leak into production publish)",
)
class T1LiveHarness(unittest.TestCase):
    def test_t1_harness_entry_real_rpc(self):
        from fastapi.testclient import TestClient
        from app.harness.server import app
        client = TestClient(app)
        run_id = os.environ.get("RWA_T1_RUN_ID") or "t1-20260905-live"
        r = client.post("/api/rwa/onchain", json={
            "mission_id": "rwa-chain-connect-20260905",
            "decision_origin": "USER",
            "run_id": run_id,
        })
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body.get("receipts"))
        usyc = next((x for x in body["receipts"] if x.get("symbol") == "USYC" and x.get("chain") == "ethereum"), None)
        self.assertIsNotNone(usyc)
        self.assertTrue(usyc.get("receipt_id"))
        self.assertEqual(usyc.get("status"), "EXECUTED", usyc.get("factual_payload", {}).get("error"))
        self.assertIsNotNone(usyc["factual_payload"].get("supply_units"))
        g = client.get("/api/rwa/onchain")
        self.assertEqual(g.status_code, 200)
        got = g.json()
        match = next((x for x in got.get("receipts") or [] if x.get("receipt_id") == usyc["receipt_id"]), None)
        self.assertIsNotNone(match)
        self.assertEqual(match["factual_payload"].get("supply_units"), usyc["factual_payload"].get("supply_units"))
        self.assertEqual(match.get("observed_at") or match["factual_payload"].get("observed_at"),
                         usyc.get("observed_at") or usyc["factual_payload"].get("observed_at"))
        ev = provenance.read_events()
        hit = next((e for e in ev if e.get("event_hash") == usyc["receipt_id"]), None)
        self.assertIsNotNone(hit)
        body_row = {k: v for k, v in hit.items() if k != "event_hash"}
        import hashlib
        recomputed = hashlib.sha256(
            json.dumps(body_row, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]
        self.assertEqual(recomputed, usyc["receipt_id"])
        # prev_hash is file-global; mission-sliced verify_chain is not meaningful.


if __name__ == "__main__":
    unittest.main()
