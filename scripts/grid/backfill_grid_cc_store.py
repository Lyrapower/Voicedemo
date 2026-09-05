#!/usr/bin/env python3
"""Backfill today's ok scan_pool/offpool jsonl rows into /store/events as grid_cc_scan."""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "grid_router"
STORE = "http://127.0.0.1:8501/store/events"
TODAY = date.today().isoformat()


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def post(kind: str, entry: dict) -> bool:
    manifest = entry.get("manifest") or {}
    payload = {
        "date": TODAY,
        "lane": "grid_cc",
        "scan_kind": kind,
        "scan_slot": manifest.get("scan_slot") or "unknown",
        "ok": True,
        "result": (entry.get("result") or "")[:4000],
        "manifest": manifest,
        "ts": entry.get("ts") or utcnow(),
        "backfill": True,
    }
    body = json.dumps(
        {"source": "aether", "kind": "grid_cc_scan", "payload": payload},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        STORE,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read().decode("utf-8"))
        print("ok", kind, payload.get("scan_slot"), data.get("id"))
        return True
    except Exception as exc:
        print("fail", kind, exc, file=sys.stderr)
        return False


def backfill_file(path: Path, kind: str) -> int:
    if not path.exists():
        return 0
    n = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not entry.get("ok"):
            continue
        ts = entry.get("ts", "")
        if not ts.startswith(TODAY):
            continue
        if post(kind, entry):
            n += 1
    return n


def main() -> None:
    n = backfill_file(OUT_DIR / "scan_pool.jsonl", "pool")
    n += backfill_file(OUT_DIR / "scan_offpool.jsonl", "offpool")
    print("backfilled", n)


if __name__ == "__main__":
    main()
