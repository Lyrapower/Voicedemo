#!/usr/bin/env python3
"""Seed nexus_state/nexus.log from dryrun.log + nexus-dryrun launchd stderr."""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NEXUS = ROOT / "aether_nexus" / "nexus_state" / "nexus.log"
DRYRUN = ROOT / "aether_nexus" / "dryrun_state" / "dryrun.log"
ERR = Path.home() / "Library/Logs/demo-aether/nexus-dryrun.err.log"


def lines_for_date(text: str, date: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.startswith(date)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD")
    args = ap.parse_args()
    sources: list[str] = []
    for path in (DRYRUN, ERR):
        if path.is_file():
            sources.append(path.read_text(encoding="utf-8", errors="replace"))
    if not sources:
        raise SystemExit("no log sources found")
    blob = "\n".join(sources)
    start = args.from_date
    end = args.to_date
    picked: list[str] = []
    for ln in blob.splitlines():
        if len(ln) >= 10 and start <= ln[:10] <= end:
            picked.append(ln)
    NEXUS.parent.mkdir(parents=True, exist_ok=True)
    existing = NEXUS.read_text(encoding="utf-8", errors="replace").splitlines() if NEXUS.is_file() else []
    merged = list(dict.fromkeys(existing + picked))
    merged.sort()
    NEXUS.write_text("\n".join(merged) + ("\n" if merged else ""), encoding="utf-8")
    print(f"nexus.log lines={len(merged)} range={start}..{end}")


if __name__ == "__main__":
    main()
