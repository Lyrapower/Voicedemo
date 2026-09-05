#!/usr/bin/env python3
"""B2 — deduplicate grid_store events by payload.date per kind."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_KINDS = [
    "aether_brief",
    "aether_brief_dryrun",
    "aether_paper_daily",
    "aether_premarket_grid",
    "aether_premarket_sonnet",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.getenv("GARDEN_GATEWAY_URL", "http://127.0.0.1:8501"))
    ap.add_argument("--kinds", default=",".join(DEFAULT_KINDS))
    args = ap.parse_args()
    body = json.dumps({"source": "aether", "kinds": args.kinds.split(",")}).encode()
    req = urllib.request.Request(
        f"{args.base.rstrip('/')}/store/events/dedup",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            out = json.loads(resp.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
