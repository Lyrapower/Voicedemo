#!/usr/bin/env python3
"""One-off: backfill FIELD diary.db from grid_store grid_diary + remove test rows."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "aster-field" / "diary.db"
STORE = "http://127.0.0.1:8501/store/events?source=grid&limit=200"
BACKFILL_DATES = ["2026-07-15", "2026-07-16", "2026-07-17", "2026-07-18"]
TEST_IDS = {13, 14, 15}


def sha_chain(prev_hash: str, ts: str, text: str) -> str:
    return hashlib.sha256((prev_hash + ts + text).encode()).hexdigest()


def fetch_grid_diaries() -> dict[str, str]:
    with urllib.request.urlopen(STORE, timeout=30) as r:
        rows = json.loads(r.read().decode())
    if isinstance(rows, dict):
        rows = rows.get("events", [])
    out: dict[str, str] = {}
    for e in rows:
        if e.get("kind") != "grid_diary":
            continue
        p = e.get("payload") or {}
        date = p.get("date") or ""
        text = (p.get("text") or "").strip()
        if date in BACKFILL_DATES and text:
            out[date] = text
    missing = [d for d in BACKFILL_DATES if d not in out]
    if missing:
        raise SystemExit(f"missing grid_diary for: {missing}")
    return out


def main() -> None:
    texts = fetch_grid_diaries()
    backup = DB.with_suffix(f".bak-backfill-{datetime.now().strftime('%Y%m%d%H%M%S')}")
    shutil.copy2(DB, backup)
    print(f"backup: {backup}")

    conn = sqlite3.connect(DB)
    try:
        conn.execute("DELETE FROM entries WHERE id IN ({})".format(",".join("?" * len(TEST_IDS))), tuple(TEST_IDS))
        deleted = conn.total_changes
        print(f"deleted test rows: {deleted}")

        row = conn.execute("SELECT hash FROM entries ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = row[0] if row else ""

        for date in BACKFILL_DATES:
            exists = conn.execute(
                "SELECT 1 FROM entries WHERE ts LIKE ? LIMIT 1", (f"{date}%",)
            ).fetchone()
            if exists:
                print(f"skip {date}: already present")
                continue
            text = texts[date]
            ts = f"{date}T22:30:00"
            h = sha_chain(prev_hash, ts, text)
            conn.execute(
                "INSERT INTO entries(ts,text,prev_hash,hash) VALUES(?,?,?,?)",
                (ts, text, prev_hash, h),
            )
            prev_hash = h
            print(f"inserted {date} ({len(text)} chars)")

        conn.commit()
    finally:
        conn.close()

    # verify via API module
    import sys
    sys.path.insert(0, str(REPO / "aster-field"))
    from backend.diary_store import verify  # noqa: E402

    v = verify()
    print("integrity:", v)
    if not v.get("ok"):
        raise SystemExit("hash chain verify failed")
    print("done")


if __name__ == "__main__":
    main()
