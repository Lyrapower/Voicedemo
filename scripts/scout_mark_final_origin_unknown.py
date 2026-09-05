#!/usr/bin/env python3
"""One-shot: mark historical morning-final.md lacking origin as review_origin=unknown.

Does not guess prior substrate. LOCAL LANE v1 · T1 only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path
from zoneinfo import ZoneInfo

SCOUT = Path("/Users/ciciwang/Projects/demo/grid-scout")
_ET = ZoneInfo("America/New_York")
_BANNER_RX = re.compile(r"^>\s*review_origin\s*=", re.M)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--dir",
        default=str(SCOUT / "briefs"),
        help="briefs directory",
    )
    args = ap.parse_args()
    bdir = Path(args.dir)
    ts = dt.datetime.now(_ET).isoformat(timespec="seconds")
    marked = []
    skipped = []
    for path in sorted(bdir.glob("*-morning-final.md")):
        text = path.read_text(encoding="utf-8")
        if _BANNER_RX.search(text):
            skipped.append(path.name)
            continue
        lines = text.splitlines()
        if lines and lines[0].startswith("# "):
            title = lines[0]
            rest = "\n".join(lines[1:]).lstrip("\n")
        else:
            title = f"# {path.stem}"
            rest = text
        out = f"{title}\n\n> review_origin=unknown · review_ts={ts}\n\n{rest.lstrip()}"
        if not out.endswith("\n"):
            out += "\n"
        if args.dry_run:
            print(f"[dry-run] would mark unknown: {path.name}")
        else:
            path.write_text(out, encoding="utf-8")
            print(f"[mark] unknown ← {path.name}")
        marked.append(path.name)
    print(
        f"[done] marked={len(marked)} skipped_already_stamped={len(skipped)} dry_run={args.dry_run}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
