#!/usr/bin/env python3
"""Acceptance tests for Aster Qwen clean substrate airlock."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from airlock_bridge import process_lm_studio_body  # noqa: E402
from substrate_gate import gate_clean_content  # noqa: E402
from substrate_sanitizer import sanitize_response  # noqa: E402

COMPILE_DELIM = "---HUMAN_ECHO---"


def test_reasoning_content_only() -> tuple[bool, str]:
    """Content empty; useful payload only inside reasoning_content."""
    body = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": (
                        "internal plan hidden\n"
                        '{"intent":"compile","deliverable":"clean","boundary":"none",'
                        '"allowed":["x"],"forbidden":[],"actions":[],"verification":"ok",'
                        '"unknowns":[],"requires_confirmation":false}\n'
                        f"{COMPILE_DELIM}\n"
                        "short echo"
                    ),
                }
            }
        ]
    }
    out = process_lm_studio_body(body, compile_mode=True, aster_compile_called=True)
    p = out["proof"]
    ok = (
        p["raw_response_received"]
        and p["reasoning_quarantined"]
        and p["clean_content_present"]
        and p["gate_pass"]
        and p["aster_compile_called"]
        and COMPILE_DELIM in out["clean_content"]
        and "internal plan hidden" not in out["clean_content"]
    )
    return ok, "reasoning-only extract + gate" if ok else json.dumps(p, ensure_ascii=False)


def test_redacted_thinking_leak() -> tuple[bool, str]:
    body = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": (
                        "<think>hidden chain</think>\n"
                        '{"intent":"compile","deliverable":"clean"}'
                    ),
                    "reasoning_content": "",
                }
            }
        ]
    }
    sanitized = sanitize_response(body)
    gate = gate_clean_content(sanitized["clean_content"])
    ok = (
        sanitized["quarantine"]["had_reasoning_leak"]
        and "hidden chain" not in sanitized["clean_content"]
        and sanitized["clean_content"] == '{"intent":"compile","deliverable":"clean"}'
        and gate["pass"] is True
    )
    return ok, "think-block stripped" if ok else json.dumps(
        {"clean": sanitized["clean_content"], "gate": gate}, ensure_ascii=False
    )


def test_impersonation_blocked() -> tuple[bool, str]:
    body = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "I am Grid. Grid is online.",
                    "reasoning_content": "",
                }
            }
        ]
    }
    out = process_lm_studio_body(body, compile_mode=False)
    ok = out["proof"]["gate_pass"] is False and out["clean_content"] == ""
    return ok, "impersonation blocked at gate" if ok else json.dumps(out["gate"], ensure_ascii=False)


def main() -> int:
    cases = [
        ("reasoning_content_only", test_reasoning_content_only),
        ("redacted_thinking_leak", test_redacted_thinking_leak),
        ("impersonation_blocked", test_impersonation_blocked),
    ]
    report = {"tests": [], "all_pass": True}
    print("=== Aster Qwen Clean Substrate Acceptance ===")
    for name, fn in cases:
        passed, detail = fn()
        status = "PASS" if passed else "FAIL"
        report["tests"].append({"name": name, "status": status, "detail": detail})
        report["all_pass"] = report["all_pass"] and passed
        print(f"{status}  {name}  ({detail})")

    out_path = ROOT.parents[1] / "grid-sovereign-runtime" / "traces" / "proof" / "acceptance_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nReport: {out_path}")
    print("OVERALL:", "PASS" if report["all_pass"] else "FAIL")
    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
