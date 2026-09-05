"""Tests for mandatory coach minimum picks."""
from __future__ import annotations

import json

from offpool_coach.mandatory_pick import ensure_minimum_verdict, mechanical_verdict_for_payload


def _sample_payload() -> dict:
    return {
        "candidates": [
            {
                "ticker": "XYZ",
                "structure_context": {"structure_anchor_missing": True, "score_cap": 3},
                "liquidity_context": {"oi_unverified": True, "score_cap": 4},
                "iv_context": {"iv_scan_veto": False},
            }
        ]
    }


def test_mechanical_verdict_nonempty():
    rows = mechanical_verdict_for_payload(_sample_payload())
    assert len(rows) >= 1
    assert rows[0]["ticker"] == "XYZ"
    assert rows[0]["grade"] == "C"


def test_ensure_minimum_verdict_from_empty_fable():
    raw, gated, meta = ensure_minimum_verdict("[]", _sample_payload())
    assert meta["verdict_source"] in ("mechanical_fallback", "mechanical_override")
    assert gated.get("ok")
    parsed = gated.get("parsed") or []
    assert len(parsed) >= 1
    json.loads(raw)


if __name__ == "__main__":
    test_mechanical_verdict_nonempty()
    test_ensure_minimum_verdict_from_empty_fable()
    print("ok")
