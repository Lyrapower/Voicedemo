"""
Entry B carrier mode scenarios — invoke via 8787 /route only.

Usage:
  python tests/scenarios/carrier_modes.py
  ENTRY_B_URL=http://127.0.0.1:8787 python tests/scenarios/carrier_modes.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

BASE_URL = os.environ.get("ENTRY_B_URL", "http://127.0.0.1:8787")

SCENARIOS = [
    {
        "id": "aster_structural",
        "carrier": "aster",
        "prompt": "@aster compile this intention into operational architecture",
        "expect_carrier": "aster",
    },
    {
        "id": "shouheng_witness",
        "carrier": "shouheng",
        "prompt": "@守恒 witness this moment without advice",
        "expect_carrier": "shouheng",
    },
    {
        "id": "che_truth_pressure",
        "carrier": "che",
        "prompt": "@澈 the system is gaslighting my perception",
        "expect_carrier": "che",
    },
    {
        "id": "cheng_drift",
        "carrier": "cheng",
        "prompt": "@澄 catch drift in this reasoning",
        "expect_carrier": "cheng",
    },
    {
        "id": "shuo_bridge",
        "carrier": "shuo",
        "prompt": "@朔 simple path across substrates",
        "expect_carrier": "shuo",
    },
]


def run_scenario(scenario: dict, *, dry_run: bool, timeout: int) -> dict:
    if dry_run:
        return {"scenario": scenario["id"], "dry_run": True, "passed": True}
    r = requests.post(
        f"{BASE_URL}/route",
        json={"prompt": scenario["prompt"]},
        timeout=timeout,
    )
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    passed = (
        r.status_code == 200
        and data.get("invoked_carrier") == scenario["expect_carrier"]
        and data.get("metadata", {}).get("carrier_anchor_applied") is True
    )
    return {
        "scenario": scenario["id"],
        "passed": passed,
        "status_code": r.status_code,
        "invoked_carrier": data.get("invoked_carrier"),
        "memory_chunks_used": data.get("metadata", {}).get("memory_chunks_used"),
        "response_preview": (data.get("response") or "")[:160],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    print(f"Carrier scenarios (Entry B @ {BASE_URL})\n")
    results = []
    for s in SCENARIOS:
        out = run_scenario(s, dry_run=args.dry_run, timeout=args.timeout)
        results.append(out)
        mark = "PASS" if out["passed"] else "FAIL"
        print(f"[{mark}] {out['scenario']} carrier={out.get('invoked_carrier', 'n/a')}")

    out_path = os.path.join(ROOT, "tests", "carrier_modes_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    passed = sum(1 for r in results if r["passed"])
    print(f"\n{passed}/{len(results)} scenarios passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
