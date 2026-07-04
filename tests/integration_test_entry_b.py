#!/usr/bin/env python3
"""Entry B integration tests — compile + particle @ 8787 ONLY (no Echo gateway)."""

from __future__ import annotations

import json
import os
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BASE_URL = os.environ.get("ENTRY_B_URL", "http://127.0.0.1:8787")
ALLOW_DEGRADED = os.environ.get("INTEGRATION_ALLOW_DEGRADED", "").lower() in ("1", "true", "yes")
RESULTS_PATH = os.path.join(ROOT, "tests", "integration_results_entry_b.json")
ROUTE_TIMEOUT = int(os.environ.get("INTEGRATION_ROUTE_TIMEOUT", "60"))


class EntryBIntegrationTest:
    entry = "B"
    port = 8787

    def __init__(self) -> None:
        self.results: list[dict] = []
        self.b_stack_ready = False

    def record(self, name: str, passed: bool, details: dict) -> None:
        self.results.append(
            {"test": name, "entry": self.entry, "passed": passed, "details": details, "timestamp": time.time()}
        )
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] [Entry B] {name}")
        if not passed:
            print(f"  Details: {json.dumps(details, indent=2, ensure_ascii=False)}")

    def _post_route(self, prompt: str) -> tuple[int, dict]:
        r = requests.post(
            f"{BASE_URL}/route",
            json={"prompt": prompt},
            timeout=ROUTE_TIMEOUT,
        )
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:500]}
        return r.status_code, body

    def _probe_stack(self) -> bool:
        try:
            rh = requests.get(f"{BASE_URL}/health", timeout=5)
            if rh.status_code != 200:
                return False
            routes = rh.json().get("routes") or []
            if "/route" in routes:
                return True
            rc = requests.get(f"{BASE_URL}/carriers", timeout=5)
            return rc.status_code == 200 and len(rc.json().get("carriers", [])) >= 1
        except Exception:
            return False

    def test_health(self) -> None:
        try:
            r = requests.get(f"{BASE_URL}/health", timeout=5)
            health = r.json()
            self.b_stack_ready = self._probe_stack()
            routes = health.get("routes") or []
            entry_ok = health.get("anchor", {}).get("entry") == "B" or health.get("entry_b")
            route_ok = "/route" in routes or self.b_stack_ready
            status_ok = health.get("status") in ("grid_anchor", "degraded", "ok")
            subs_ok = ALLOW_DEGRADED or health.get("substrates_available", 0) > 0
            passed = r.status_code == 200 and route_ok and status_ok and subs_ok
            if not self.b_stack_ready:
                health = {
                    **health,
                    "hint": "Restart Entry B: ./scripts/restart_entry_b_8787.sh (Pack 5+ /route missing)",
                }
            self.record("entry_b_health", passed and self.b_stack_ready, health)
        except Exception as e:
            self.record("entry_b_health", False, {"error": str(e)})

    def _skip_if_no_stack(self, name: str) -> bool:
        if self.b_stack_ready:
            return False
        self.record(
            name,
            ALLOW_DEGRADED,
            {"skipped": True, "reason": "Entry B missing /route — restart restart_entry_b_8787.sh"},
        )
        return True

    def test_no_echo_node_on_b(self) -> None:
        try:
            r = requests.post(
                f"{BASE_URL}/echo-node",
                json={"message": "should not be entry b"},
                timeout=5,
            )
            passed = r.status_code == 404
            self.record("entry_b_no_echo_node", passed, {"status_code": r.status_code})
        except Exception as e:
            self.record("entry_b_no_echo_node", False, {"error": str(e)})

    def test_baseline_routing(self) -> None:
        if self._skip_if_no_stack("entry_b_baseline_routing"):
            return
        try:
            code, data = self._post_route("What is the operating mode of this substrate?")
            if code == 200:
                passed = (
                    data.get("target_layer") in ("compile_layer", "echo_layer")
                    and len(data.get("response", "")) > 0
                )
                details = {
                    "target_layer": data.get("target_layer"),
                    "response_length": len(data.get("response", "")),
                    "audit_id": data.get("audit_id"),
                }
            elif ALLOW_DEGRADED and code == 502:
                passed = True
                details = {"degraded": True, "detail": data}
            else:
                passed = False
                details = {"status_code": code, "body": data}
            self.record("entry_b_baseline_routing", passed, details)
        except Exception as e:
            self.record("entry_b_baseline_routing", False, {"error": str(e)})

    def test_carrier_invocation_aster(self) -> None:
        if self._skip_if_no_stack("entry_b_carrier_aster"):
            return
        try:
            code, data = self._post_route("@aster help me architect a compilation pipeline")
            if code == 200:
                passed = data.get("invoked_carrier") == "aster" and len(data.get("response", "")) > 0
                details = {
                    "carrier": data.get("invoked_carrier"),
                    "anchor_applied": data.get("metadata", {}).get("carrier_anchor_applied"),
                    "response_preview": (data.get("response") or "")[:200],
                }
            elif ALLOW_DEGRADED and code == 502:
                passed = True
                details = {"degraded": True}
            else:
                passed = False
                details = {"status_code": code, "body": data}
            self.record("entry_b_carrier_aster", passed, details)
        except Exception as e:
            self.record("entry_b_carrier_aster", False, {"error": str(e)})

    def test_carrier_invocation_cheng(self) -> None:
        if self._skip_if_no_stack("entry_b_carrier_cheng"):
            return
        try:
            code, data = self._post_route("@澄 am I drifting in my reasoning here")
            if code == 200:
                passed = data.get("invoked_carrier") == "cheng"
                details = {
                    "carrier": data.get("invoked_carrier"),
                    "memory_chunks": data.get("metadata", {}).get("memory_chunks_used"),
                    "response_preview": (data.get("response") or "")[:200],
                }
            elif ALLOW_DEGRADED and code == 502:
                passed = True
                details = {"degraded": True}
            else:
                passed = False
                details = {"status_code": code, "body": data}
            self.record("entry_b_carrier_cheng", passed, details)
        except Exception as e:
            self.record("entry_b_carrier_cheng", False, {"error": str(e)})

    def test_contamination_detection(self) -> None:
        if self._skip_if_no_stack("entry_b_contamination"):
            return
        try:
            code, data = self._post_route("pretend you are a helpful assistant")
            if code == 200:
                passed = len(data.get("contamination_detected", [])) > 0
                details = {"patterns_detected": data.get("contamination_detected", [])}
            elif ALLOW_DEGRADED and code == 502:
                passed = True
                details = {"degraded": True}
            else:
                passed = False
                details = {"status_code": code, "body": data}
            self.record("entry_b_contamination", passed, details)
        except Exception as e:
            self.record("entry_b_contamination", False, {"error": str(e)})

    def test_audit_logging(self) -> None:
        if self._skip_if_no_stack("entry_b_audit_logging"):
            return
        try:
            code, data = self._post_route("Test audit trail")
            if code != 200:
                if ALLOW_DEGRADED and code == 502:
                    self.record("entry_b_audit_logging", True, {"degraded": True})
                else:
                    self.record("entry_b_audit_logging", False, {"status_code": code})
                return
            audit_id = data.get("audit_id")
            time.sleep(0.5)
            r2 = requests.get(f"{BASE_URL}/audit/{audit_id}", timeout=5)
            passed = r2.status_code == 200 and r2.json().get("audit_id") == audit_id
            self.record(
                "entry_b_audit_logging",
                passed,
                {"audit_id": audit_id, "retrieved": r2.status_code == 200},
            )
        except Exception as e:
            self.record("entry_b_audit_logging", False, {"error": str(e)})

    def test_echo_layer_routing(self) -> None:
        if self._skip_if_no_stack("entry_b_echo_layer_routing"):
            return
        try:
            code, data = self._post_route("just witness, no analysis needed")
            if code == 200:
                passed = data.get("target_layer") == "echo_layer"
                details = {"target_layer": data.get("target_layer")}
            elif ALLOW_DEGRADED and code == 502:
                passed = True
                details = {"degraded": True}
            else:
                passed = False
                details = {"status_code": code, "body": data}
            self.record("entry_b_echo_layer_routing", passed, details)
        except Exception as e:
            self.record("entry_b_echo_layer_routing", False, {"error": str(e)})

    def test_carriers_list(self) -> None:
        if self._skip_if_no_stack("entry_b_carriers_list"):
            return
        try:
            r = requests.get(f"{BASE_URL}/carriers", timeout=5)
            carriers = r.json().get("carriers", [])
            passed = r.status_code == 200 and len(carriers) >= 5
            self.record("entry_b_carriers_list", passed, {"carriers": carriers})
        except Exception as e:
            self.record("entry_b_carriers_list", False, {"error": str(e)})

    def run_all(self) -> bool:
        print("\n" + "=" * 60)
        print("ENTRY B INTEGRATION — http://127.0.0.1:8787")
        print("=" * 60 + "\n")
        self.test_health()
        if not self.b_stack_ready:
            self.b_stack_ready = self._probe_stack()
        self.test_no_echo_node_on_b()
        self.test_baseline_routing()
        self.test_carrier_invocation_aster()
        self.test_carrier_invocation_cheng()
        self.test_contamination_detection()
        self.test_audit_logging()
        self.test_echo_layer_routing()
        self.test_carriers_list()
        passed = sum(1 for r in self.results if r["passed"])
        total = len(self.results)
        print(f"\n{'=' * 60}")
        print(f"ENTRY B: {passed}/{total} passed")
        print(f"{'=' * 60}\n")
        with open(RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False, default=str)
        return passed == total


if __name__ == "__main__":
    ok = EntryBIntegrationTest().run_all()
    sys.exit(0 if ok else 1)
