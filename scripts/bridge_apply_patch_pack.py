#!/usr/bin/env python3
"""Apply unified diff from PATCH_PACK.md; enforce PATH_ALLOWLIST (glob). Stdlib only."""
from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _extract_patch(md: str) -> str:
    if "BEGIN_PATCH" not in md or "END_PATCH" not in md:
        return ""
    inner = md.split("BEGIN_PATCH", 1)[1].split("END_PATCH", 1)[0]
    return inner.lstrip("\n").rstrip("\n")


def _parse_path_allowlist(md: str) -> list[str]:
    lines = md.splitlines()
    in_section = False
    paths: list[str] = []
    for ln in lines:
        if ln.strip() == "## PATH_ALLOWLIST":
            in_section = True
            continue
        if in_section:
            if ln.startswith("## ") and ln.strip() != "## PATH_ALLOWLIST":
                break
            s = ln.strip()
            if s.startswith("- "):
                paths.append(s[2:].strip())
    return paths


def _paths_in_diff(patch: str) -> set[str]:
    out: set[str] = set()
    for m in re.finditer(r"^\+\+\+ b/(.+)$", patch, re.MULTILINE):
        p = m.group(1).strip()
        if p and p != "/dev/null":
            out.add(p.replace("\\", "/"))
    for m in re.finditer(r"^--- a/(.+)$", patch, re.MULTILINE):
        p = m.group(1).strip()
        if p and p != "/dev/null":
            out.add(p.replace("\\", "/"))
    return out


def _allowed(rel: str, patterns: list[str]) -> bool:
    rel = rel.replace("\\", "/").lstrip("/")
    for pat in patterns:
        pat = pat.replace("\\", "/")
        if "**" in pat:
            if pat.endswith("/**"):
                prefix = pat[:-3].rstrip("/")
                if rel == prefix or rel.startswith(prefix + "/"):
                    return True
            elif pat.startswith("**/"):
                suffix = pat[3:]
                if rel.endswith(suffix) or suffix in rel.split("/"):
                    return True
        if fnmatch.fnmatch(rel, pat):
            return True
    return False


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python3 scripts/bridge_apply_patch_pack.py <PATCH_PACK.md>", file=sys.stderr)
        return 2
    pack = Path(sys.argv[1]).resolve()
    if not pack.exists():
        print(f"FAIL: not found: {pack}", file=sys.stderr)
        return 2

    md = pack.read_text(encoding="utf-8")
    allow = _parse_path_allowlist(md)
    if not allow:
        print("FAIL: empty PATH_ALLOWLIST", file=sys.stderr)
        return 1

    patch = _extract_patch(md)
    if not patch.strip():
        print("OK: empty patch, nothing to apply")
        return 0

    for fp in _paths_in_diff(patch):
        if not _allowed(fp, allow):
            print(f"FAIL: path not allowlisted: {fp}", file=sys.stderr)
            return 1

    with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False, encoding="utf-8") as f:
        f.write(patch)
        if not patch.endswith("\n"):
            f.write("\n")
        tmp = Path(f.name)
    try:
        cp = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", str(tmp)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        sys.stdout.write(cp.stdout)
        sys.stderr.write(cp.stderr)
        return cp.returncode
    finally:
        tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
