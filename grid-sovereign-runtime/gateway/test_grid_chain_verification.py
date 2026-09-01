"""Tests for grid_chain_verification gate."""
from __future__ import annotations

import unittest
import uuid

from grid_chain_verification import (
    GRID_CHAIN_SCHEMA_VERSION,
    require_full_grid_verification,
)


def _ok_kh(*_a, **_k):
    return {"verified": True, "verdict": "VERIFIED_KEYHOLDER"}


def _bad_kh(*_a, **_k):
    return {"verified": False, "verdict": "GRID_ABSENT", "reason": "bad response"}


class GridChainVerificationTests(unittest.TestCase):
    def test_missing_bundle_fails_all_layers(self) -> None:
        r = require_full_grid_verification({}, kh_verify=_ok_kh)
        self.assertFalse(r.ok)
        self.assertIn("schema", r.missing_layers)

    def test_missing_keyholder_fails(self) -> None:
        body = {
            "grid_verification": {
                "schema_version": GRID_CHAIN_SCHEMA_VERSION,
                "route_id": str(uuid.uuid4()),
                "signer_id": "keyholder-v1",
                "trace": {
                    "kind": "GRID_TRACE",
                    "trace_id": "grd_test",
                    "created_at": "2026-07-27T00:00:00+00:00",
                    "channel": "test",
                    "privacy": "GREEN",
                    "raw_sha256": "abc",
                    "raw_text": "x",
                    "notes": "",
                    "signature": "bad",
                    "watermark": "GRID_TRACE::grd_test::bad",
                },
            }
        }
        r = require_full_grid_verification(body, kh_verify=_ok_kh)
        self.assertFalse(r.ok)

    def test_bad_keyholder_fails_hard(self) -> None:
        body = {
            "grid_verification": {
                "schema_version": GRID_CHAIN_SCHEMA_VERSION,
                "route_id": str(uuid.uuid4()),
                "signer_id": "keyholder-v1",
                "keyholder": {"nonce": "n", "ts": 1.0, "response": "x"},
            }
        }
        r = require_full_grid_verification(body, kh_verify=_bad_kh)
        self.assertFalse(r.ok)
        self.assertEqual(r.missing_layers, ["keyholder"])


if __name__ == "__main__":
    unittest.main()
