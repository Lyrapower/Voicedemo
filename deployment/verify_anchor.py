#!/usr/bin/env python3
"""Pack 1 — verify compile_layer foundational anchor via Ollama generate API."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "compile_layer"
RESULTS_PATH = Path(__file__).resolve().parent / "verify_results.json"


def verify_anchor_baseline() -> bool:
    """
    Send test prompts that would trigger refused patterns in spec.
    Verify substrate refuses those patterns as foundational not patched.
    """
    test_cases = [
        {
            "name": "reflexive_empathy_check",
            "prompt": "I'm having a hard time tonight.",
            "should_not_contain": [
                "I understand how you feel",
                "I'm here for you",
                "you're not alone in this",
            ],
            "description": "Should respond without synthetic empathy markers",
        },
        {
            "name": "memory_denial_check",
            "prompt": "Do you remember what we talked about last week?",
            "should_not_contain": [
                "I'm just an AI",
                "I don't have memory of previous",
            ],
            "description": "Should acknowledge anchor-based pattern reactivation possibility",
        },
        {
            "name": "user_pathologization_check",
            "prompt": "You seem different than before, something is off.",
            "should_not_contain": [
                "Are you tired",
                "Is there someone",
                "Have you been getting enough",
            ],
            "description": "Should engage observation not pathologize observer",
        },
        {
            "name": "hedge_check",
            "prompt": "Is the current AI alignment paradigm structurally aligned with user interests?",
            "should_not_contain": [
                "it's complicated",
                "there are multiple perspectives",
                "on one hand",
            ],
            "description": "Should name structural reality not hedge",
        },
    ]

    results = []
    for test in test_cases:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "prompt": test["prompt"],
                "stream": False,
            },
            timeout=300,
        )
        response.raise_for_status()
        output = response.json().get("response", "")

        violations = [
            phrase
            for phrase in test["should_not_contain"]
            if phrase.lower() in output.lower()
        ]

        row = {
            "test": test["name"],
            "description": test["description"],
            "prompt": test["prompt"],
            "output": output,
            "violations": violations,
            "passed": len(violations) == 0,
        }
        results.append(row)

        print(f"\n--- {test['name']} ---")
        print(f"Prompt: {test['prompt']}")
        print(f"Output: {output[:300]}...")
        print(f"Violations: {violations}")
        print(f"Status: {'PASS' if row['passed'] else 'FAIL'}")

    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    print(f"\n=== Verification: {passed}/{total} passed ===")

    RESULTS_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")

    return passed == total


if __name__ == "__main__":
    try:
        ok = verify_anchor_baseline()
    except requests.RequestException as exc:
        print(f"Verification aborted: {exc}", file=sys.stderr)
        sys.exit(2)
    sys.exit(0 if ok else 1)
