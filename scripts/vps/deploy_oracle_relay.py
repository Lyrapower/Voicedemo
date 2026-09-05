#!/usr/bin/env python3
"""Copy VPS bootstrap files to clipboard-friendly paths + optional scp helper."""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VPS = ROOT / "scripts" / "vps"


def main() -> None:
    ap = argparse.ArgumentParser(description="Show VPS bootstrap paths")
    ap.add_argument("--host", help="Oracle instance public IP for scp one-liner")
    args = ap.parse_args()
    boot = VPS / "oracle_free_bootstrap.sh"
    readme = VPS / "README_ORACLE_FREE.md"
    print("README:", readme)
    print("Bootstrap:", boot)
    if args.host:
        print()
        print("scp one-liner:")
        print(f"  scp {boot} ubuntu@{args.host}:/tmp/ && ssh ubuntu@{args.host} 'sudo bash /tmp/oracle_free_bootstrap.sh'")


if __name__ == "__main__":
    main()
