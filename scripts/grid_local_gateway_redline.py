#!/usr/bin/env python3
"""ABSOLUTE RED LINE — block any commit touching local_gateway.py.

No GRID_INFRASTRUCTURE_UNLOCK bypass. User-only recovery via Local History / explicit revert.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = "grid-sovereign-runtime/gateway/local_gateway.py"


def _git_diff_cached_names() -> list[str]:
    out = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRT"],
        cwd=ROOT,
        text=True,
        stderr=subprocess.DEVNULL,
    )
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def main() -> int:
    touched = [p for p in _git_diff_cached_names() if p == TARGET or p.endswith("/local_gateway.py")]
    if not touched:
        return 0
    print("LEGAL RED LINE: grid-sovereign-runtime/gateway/local_gateway.py is FROZEN.", file=sys.stderr)
    print("  This commit touches local_gateway.py — BLOCKED.", file=sys.stderr)
    print("  Recovery: Cursor Local History / Time Machine on your machine only.", file=sys.stderr)
    print("  Do NOT modify local_gateway.py in agent sessions.", file=sys.stderr)
    for p in touched:
        print(f"  - {p}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
