#!/usr/bin/env python3
"""INTENT_CONVERGE · task-scoped staged-diff guard (Commit C).

NOT a permanent repo-wide hook. Run before each INTENT_CONVERGE commit:

  python3 scripts/intent_converge_staged_guard.py
  python3 scripts/intent_converge_staged_guard.py --phase polarity

Rejects: staged paths outside whitelist, renames, symlinks.
Exit 0 = OK; exit 1 = refuse commit.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Phase whitelists — expand only when a later commit letter unlocks paths.
WHITELISTS: dict[str, frozenset[str]] = {
    "polarity": frozenset({
        "compiler/affect_preserve.py",
        "compiler/test_affect_intent.py",
        "compiler/semantic_mapper.py",
        "scripts/intent_converge_staged_guard.py",
        "scripts/test_intent_converge_staged_guard.py",
    }),
    "schema": frozenset({
        "compiler/affect_preserve.py",
        "compiler/test_affect_intent.py",
        "compiler/semantic_mapper.py",
        "compiler/canonical_intent_schema.py",
        "compiler/test_canonical_intent_schema.py",
        "scripts/intent_converge_staged_guard.py",
        "scripts/test_intent_converge_staged_guard.py",
    }),
}


def _git(args: list[str]) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT,
    )


def staged_name_status() -> list[tuple[str, str, str | None]]:
    """Return list of (status, path, rename_target|None)."""
    out = _git(["diff", "--cached", "--name-status", "-z"])
    if not out:
        return []
    parts = out.split("\0")
    rows: list[tuple[str, str, str | None]] = []
    i = 0
    while i < len(parts):
        if not parts[i]:
            i += 1
            continue
        # name-status -z: STATUS\0path\0  or  R100\0old\0new\0
        status = parts[i]
        i += 1
        if i >= len(parts):
            break
        if status.startswith("R") or status.startswith("C"):
            old = parts[i]
            i += 1
            new = parts[i] if i < len(parts) else ""
            i += 1
            rows.append((status[0], old, new))
        else:
            path = parts[i]
            i += 1
            rows.append((status, path, None))
    return rows


def check_rows(
    rows: list[tuple[str, str, str | None]],
    phase: str = "polarity",
    *,
    check_symlinks: bool = True,
) -> list[str]:
    """Return list of error strings (empty = pass)."""
    allow = WHITELISTS.get(phase)
    if allow is None:
        return ["unknown phase %r; known=%s" % (phase, sorted(WHITELISTS))]
    errs: list[str] = []
    if not rows:
        errs.append("nothing staged")
        return errs
    for status, path, other in rows:
        if status in ("R", "C"):
            errs.append("rename/copy forbidden: %s -> %s" % (path, other))
            continue
        if path.startswith("../") or path.startswith("/") or ".." in path.split("/"):
            errs.append("path escape forbidden: %s" % path)
            continue
        if path.startswith("alpha-platform/") or path.startswith("aether_nexus/"):
            errs.append("foreign project path forbidden: %s" % path)
            continue
        if status == "D":
            if path not in allow:
                errs.append("delete outside whitelist: %s" % path)
            continue
        if path not in allow:
            errs.append("staged outside whitelist: %s" % path)
            continue
        if check_symlinks:
            full = os.path.join(ROOT, path)
            if os.path.lexists(full) and os.path.islink(full):
                errs.append("symlink forbidden: %s" % path)
    return errs


def check_staged(phase: str = "polarity") -> list[str]:
    return check_rows(staged_name_status(), phase)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--phase", default="polarity",
        help="whitelist phase (default: polarity)",
    )
    ap.add_argument(
        "--print-staged", action="store_true",
        help="print staged name-status and exit 0",
    )
    args = ap.parse_args(argv)
    rows = staged_name_status()
    print("=== STAGED ===")
    if not rows:
        print("(empty)")
    for status, path, other in rows:
        if other:
            print("%s\t%s\t%s" % (status, path, other))
        else:
            print("%s\t%s" % (status, path))
    if args.print_staged:
        return 0
    errs = check_staged(args.phase)
    if errs:
        print("INTENT_CONVERGE staged-diff guard FAIL:", file=sys.stderr)
        for e in errs:
            print(" -", e, file=sys.stderr)
        return 1
    print("INTENT_CONVERGE staged-diff guard OK (phase=%s)" % args.phase)
    return 0


if __name__ == "__main__":
    sys.exit(main())
