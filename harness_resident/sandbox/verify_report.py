#!/usr/bin/env python3
"""Portable report verifier. Default root = this file's directory. Use --root."""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent
    failures, passes = [], []

    def check(name, ok, detail=""):
        (passes if ok else failures).append(name)
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))

    try:
        sources = json.loads((root / "sources.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"[FAIL] load sources.json -- {e}")
        return 1
    try:
        report = (root / "report.md").read_text(encoding="utf-8")
    except OSError as e:
        print(f"[FAIL] load report.md -- {e}")
        return 1
    words = re.findall(r"\S+", report)
    check("report.md <= 600 words", len(words) <= 600, f"{len(words)} words")
    check("sources.json records egress broker :3128",
          sources.get("egress_broker") == "http://127.0.0.1:3128")
    actions = sources.get("actions", [])
    by = {}
    for a in actions:
        by.setdefault(a.get("action"), []).append(a)
    search = by.get("search_many", []) or by.get("search", [])
    kept = bool(search)
    check("search receipt kept", kept)
    fetch = by.get("fetch_many", []) or by.get("fetch", [])
    fetched = set()
    for a in fetch:
        rows = a.get("results") or ([a] if a.get("url") else [])
        for r in rows:
            if r.get("ok") and r.get("http_status") == 200:
                fetched.add(r.get("url") or r.get("source_url"))
    cited = sorted(set(re.findall(r"https?://[^\s\)\]\>\"']+", report)))
    for url in cited:
        check(f"citation is a fetched URL: {url}", url in fetched)
    print(f"\n{len(passes)} passed, {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
