#!/usr/bin/env python3
"""
Pack 7 — run Entry A and Entry B integration suites separately (never merged).

  python tests/integration_test.py           # both, separate result files
  python tests/integration_test.py --entry-a
  python tests/integration_test.py --entry-b
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(script: str) -> int:
    path = os.path.join(ROOT, "tests", script)
    print(f"\n>>> Running {script}\n")
    return subprocess.call([sys.executable, path], cwd=ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description="Dual-entry integration runner (A/B separate)")
    parser.add_argument("--entry-a", action="store_true", help="Run Entry A (8500) only")
    parser.add_argument("--entry-b", action="store_true", help="Run Entry B (8787) only")
    args = parser.parse_args()

    run_a = args.entry_a or (not args.entry_a and not args.entry_b)
    run_b = args.entry_b or (not args.entry_a and not args.entry_b)

    codes: list[int] = []
    summary: dict = {"timestamp": time.time(), "entries": {}}

    if run_a:
        codes.append(_run("integration_test_entry_a.py"))
        a_path = os.path.join(ROOT, "tests", "integration_results_entry_a.json")
        if os.path.exists(a_path):
            with open(a_path, encoding="utf-8") as f:
                rows = json.load(f)
            summary["entries"]["A"] = {
                "passed": sum(1 for r in rows if r["passed"]),
                "total": len(rows),
            }

    if run_b:
        codes.append(_run("integration_test_entry_b.py"))
        b_path = os.path.join(ROOT, "tests", "integration_results_entry_b.json")
        if os.path.exists(b_path):
            with open(b_path, encoding="utf-8") as f:
                rows = json.load(f)
            summary["entries"]["B"] = {
                "passed": sum(1 for r in rows if r["passed"]),
                "total": len(rows),
            }

    out = os.path.join(ROOT, "tests", "integration_results_summary.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print("DUAL-ENTRY SUMMARY (A and B tested separately)")
    print(json.dumps(summary["entries"], indent=2))
    print("=" * 60 + "\n")

    return 0 if codes and all(c == 0 for c in codes) else 1


if __name__ == "__main__":
    sys.exit(main())
