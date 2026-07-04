#!/usr/bin/env python3
"""Entry A integration tests — Echo gateway @ 8500 ONLY (no compile /route)."""

from __future__ import annotations

import json
import os
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BASE_URL = os.environ.get("ENTRY_A_URL", "http://127.0.0.1:8500")
RESULTS_PATH = os.path.join(ROOT, "tests", "integration_results_entry_a.json")


class EntryAIntegrationTest:
    entry = "A"
    port = 8500

    def __init__(self) -> None:
        self.results: list[dict] = []

    def record(self, name: str, passed: bool, details: dict) -> None:
        self.results.append(
            {"test": name, "entry": self.entry, "passed": passed, "details": details, "timestamp": time.time()}
        )
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] [Entry A] {name}")
        if not passed:
            print(f"  Details: {json.dumps(details, indent=2, ensure_ascii=False)}")

    def test_health(self) -> None:
        try:
            r = requests.get(f"{BASE_URL}/health", timeout=5)
            health = r.json()
            port = health.get("port") or health.get("anchor", {}).get("port")
            entry = health.get("entry") or health.get("anchor", {}).get("entry")
            service = health.get("service") or ""
            passed = (
                r.status_code == 200
                and health.get("status") in ("grid_anchor", "ok")
                and port == 8500
                and (entry == "A" or "entry-a" in service)
            )
            self.record("entry_a_health", passed, health)
        except Exception as e:
            self.record("entry_a_health", False, {"error": str(e)})

    def test_echo_node(self) -> None:
        try:
            r = requests.post(
                f"{BASE_URL}/echo-node",
                json={"message": "sovereign coherence ping echo"},
                timeout=15,
            )
            data = r.json()
            passed = r.status_code == 200 and bool(data.get("response")) and "mode" in data
            self.record(
                "entry_a_echo_node",
                passed,
                {"mode": data.get("mode"), "response_preview": (data.get("response") or "")[:120]},
            )
        except Exception as e:
            self.record("entry_a_echo_node", False, {"error": str(e)})

    def test_descriptor_and_context(self) -> None:
        try:
            rd = requests.get(f"{BASE_URL}/descriptor", timeout=5)
            rc = requests.get(f"{BASE_URL}/context", timeout=5)
            passed = rd.status_code == 200 and rc.status_code == 200 and "model_descriptor" in rd.json()
            self.record(
                "entry_a_descriptor_context",
                passed,
                {"descriptor_ok": rd.status_code == 200, "context_ok": rc.status_code == 200},
            )
        except Exception as e:
            self.record("entry_a_descriptor_context", False, {"error": str(e)})

    def test_no_compile_route(self) -> None:
        """Entry A must NOT expose Pack 4/5 /route (compile lives on 8787)."""
        try:
            r = requests.post(
                f"{BASE_URL}/route",
                json={"prompt": "must not exist on A"},
                timeout=5,
            )
            passed = r.status_code == 404
            self.record("entry_a_no_compile_route", passed, {"status_code": r.status_code})
        except Exception as e:
            self.record("entry_a_no_compile_route", False, {"error": str(e)})

    def test_separation_from_b(self) -> None:
        """Health must identify Entry A service, not Entry B compile router."""
        try:
            r = requests.get(f"{BASE_URL}/health", timeout=5)
            health = r.json()
            routes = health.get("routes") or {}
            route_list = routes if isinstance(routes, list) else list(routes.keys())
            passed = (
                health.get("service") == "entry-a-echo-gateway-8500"
                and "/route" not in route_list
            )
            self.record(
                "entry_a_separation",
                passed,
                {"service": health.get("service"), "routes": routes},
            )
        except Exception as e:
            self.record("entry_a_separation", False, {"error": str(e)})

    def run_all(self) -> bool:
        print("\n" + "=" * 60)
        print("ENTRY A INTEGRATION — http://127.0.0.1:8500")
        print("=" * 60 + "\n")
        self.test_health()
        self.test_echo_node()
        self.test_descriptor_and_context()
        self.test_no_compile_route()
        self.test_separation_from_b()
        passed = sum(1 for r in self.results if r["passed"])
        total = len(self.results)
        print(f"\n{'=' * 60}")
        print(f"ENTRY A: {passed}/{total} passed")
        print(f"{'=' * 60}\n")
        with open(RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False, default=str)
        return passed == total


if __name__ == "__main__":
    ok = EntryAIntegrationTest().run_all()
    sys.exit(0 if ok else 1)
