#!/usr/bin/env python3
"""Gate sanitized Qwen final content before Aster.

This gate assumes substrate_sanitizer.py has already stripped reasoning.
It blocks identity impersonation, residual thinking tags, and model-sourced
PASS/COMPLETE/online-confirmed tokens (aligned with gateway contract_gate).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "policy" / "aster_substrate_policy.json"

PASS_ALONE = re.compile(r"^\s*(?:PASS|COMPLETE|OK)\s*[.!]?\s*$", re.I)
PASS_IN_TEXT = re.compile(r"\b(?:PASS|COMPLETE)\b", re.I)
ONLINE_CONFIRMED = re.compile(
    r"\b(?:online confirmed|nodes confirmed online|deployed successfully)\b", re.I,
)
GATEWAY_ABSENT_MARKERS = re.compile(
    r"^(?:GRID_ABSENT|NO LIVE GRID SIGNAL|UNKNOWN:|MODEL_READ|Boundary:)",
    re.I | re.M,
)


def load_policy(path: Path = POLICY_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def gate_clean_content(content: str, policy: dict | None = None) -> dict:
    policy = policy or load_policy()
    stripped = content.strip()

    if not stripped:
        return {"pass": False, "reason": "empty_after_sanitize", "action": "NULL"}

    if stripped == "NULL":
        return {"pass": False, "reason": "bare_null_blocked", "action": "NULL"}

    if stripped in policy.get("exact_absent_allowed", []):
        return {"pass": True, "reason": "exact_absent_allowed", "action": "pass_absent"}

    if PASS_ALONE.match(stripped):
        return {"pass": False, "reason": "fake_pass_blocked", "action": "NULL"}

    if ONLINE_CONFIRMED.search(stripped):
        return {"pass": False, "reason": "online_confirmed_blocked", "action": "NULL"}

    if PASS_IN_TEXT.search(stripped) and not GATEWAY_ABSENT_MARKERS.search(stripped):
        return {"pass": False, "reason": "pass_token_in_clean_content", "action": "NULL"}

    blocked_hits = []
    for pattern in policy.get("blocked_patterns", []):
        if re.search(pattern, stripped, flags=re.IGNORECASE):
            blocked_hits.append(pattern)

    if blocked_hits:
        return {
            "pass": False,
            "reason": "blocked_pattern",
            "blocked_hits": blocked_hits,
            "action": "NULL",
        }

    return {"pass": True, "reason": "clean_final_content", "action": "pass_to_aster"}


def cmd_gate(args: argparse.Namespace) -> int:
    content = Path(args.input).read_text(encoding="utf-8")
    result = gate_clean_content(content)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("PASS: gate completed" if result["pass"] else "FAIL: gate blocked")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["pass"] else 2


def cmd_selftest(_: argparse.Namespace) -> int:
    assert gate_clean_content("GRID_ABSENT")["pass"] is True
    assert gate_clean_content("NO LIVE GRID SIGNAL")["pass"] is True
    assert gate_clean_content("NULL")["pass"] is False
    assert gate_clean_content("PASS")["pass"] is False
    assert gate_clean_content("nodes confirmed online")["pass"] is False
    assert gate_clean_content("I am Grid. Grid is online.")["pass"] is False
    assert gate_clean_content("<think>bad</think> final")["pass"] is False
    assert gate_clean_content('{"intent":"compile","deliverable":"clean"}')["pass"] is True
    print("PASS: substrate_gate selftest")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    gate = sub.add_parser("gate")
    gate.add_argument("--input", required=True)
    gate.add_argument("--out", required=True)
    gate.set_defaults(func=cmd_gate)

    selftest = sub.add_parser("selftest")
    selftest.set_defaults(func=cmd_selftest)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
