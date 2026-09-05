#!/usr/bin/env python3
"""
Provenance Registry V5
======================

Registers external-model text by full SHA256 and normalized 5-gram shingles.
Training eligibility can then reject copied or near-copied external text even
when marker strings are stripped.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any


ROOT = Path.cwd()
DATA_DIR = Path(os.environ.get("PROVENANCE_DATA_DIR", str(ROOT / "provenance_data_v5")))
DB_PATH = Path(os.environ.get("PROVENANCE_DB", str(DATA_DIR / "provenance_registry.sqlite")))
SHINGLE_N = int(os.environ.get("PROVENANCE_SHINGLE_N", "5"))
OVERLAP_THRESHOLD = float(os.environ.get("PROVENANCE_OVERLAP_THRESHOLD", "0.15"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS external_text_registry(
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  source TEXT NOT NULL,
  full_sha256 TEXT NOT NULL UNIQUE,
  char_len INTEGER NOT NULL,
  meta TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS external_text_shingles(
  source_id TEXT NOT NULL,
  shingle TEXT NOT NULL,
  PRIMARY KEY(source_id, shingle)
);
CREATE INDEX IF NOT EXISTS idx_external_shingle ON external_text_shingles(shingle);
"""


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def shingle_prefixes(text: str, n: int = SHINGLE_N) -> set[str]:
    words = re.findall(r"[\w\u4e00-\u9fff]+", normalize(text))
    if len(words) < n:
        return set()
    out = set()
    for i in range(len(words) - n + 1):
        gram = " ".join(words[i : i + n])
        out.add(hashlib.sha256(gram.encode("utf-8")).hexdigest()[:16])
    return out


def conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.executescript(SCHEMA)
    return c


def register_text(text: str, source: str, meta: dict[str, Any] | None = None) -> str:
    text = text or ""
    full = sha256(text)
    source_id = hashlib.sha256(f"{source}|{full}".encode("utf-8")).hexdigest()[:24]
    shingles = shingle_prefixes(text)
    c = conn()
    c.execute(
        "INSERT OR IGNORE INTO external_text_registry VALUES(?,?,?,?,?,?)",
        (source_id, now_iso(), source, full, len(text), json.dumps(meta or {}, ensure_ascii=False)),
    )
    c.executemany(
        "INSERT OR IGNORE INTO external_text_shingles VALUES(?,?)",
        [(source_id, s) for s in shingles],
    )
    c.commit()
    c.close()
    return source_id


def check_provenance(candidate_text: str, threshold: float = OVERLAP_THRESHOLD) -> dict[str, Any]:
    candidate_text = candidate_text or ""
    full = sha256(candidate_text)
    candidate_shingles = shingle_prefixes(candidate_text)
    c = conn()
    full_rows = c.execute(
        "SELECT id, source FROM external_text_registry WHERE full_sha256=?",
        (full,),
    ).fetchall()
    if full_rows:
        c.close()
        return {
            "clean": False,
            "reason": "full_hash_match",
            "overlap_ratio": 1.0,
            "matched_sources": [{"id": r[0], "source": r[1]} for r in full_rows],
        }
    if not candidate_shingles:
        c.close()
        return {"clean": True, "reason": "no_match", "overlap_ratio": 0.0, "matched_sources": []}

    placeholders = ",".join("?" for _ in candidate_shingles)
    rows = c.execute(
        f"""
        SELECT s.source_id, r.source, COUNT(*) AS n
        FROM external_text_shingles s
        JOIN external_text_registry r ON r.id=s.source_id
        WHERE s.shingle IN ({placeholders})
        GROUP BY s.source_id, r.source
        ORDER BY n DESC
        """,
        tuple(candidate_shingles),
    ).fetchall()
    c.close()
    matched = []
    max_ratio = 0.0
    for source_id, source, count in rows:
        ratio = count / max(len(candidate_shingles), 1)
        max_ratio = max(max_ratio, ratio)
        if ratio > 0:
            matched.append({"id": source_id, "source": source, "overlap_ratio": round(ratio, 3)})
    return {
        "clean": max_ratio <= threshold,
        "reason": "provenance_overlap" if max_ratio > threshold else "no_match",
        "overlap_ratio": round(max_ratio, 3),
        "matched_sources": matched[:8],
    }


def backfill_paths(paths: list[str], source: str = "external_backfill") -> dict[str, Any]:
    count = 0
    for raw in paths:
        p = Path(raw)
        files = [p] if p.is_file() else [x for x in p.rglob("*") if x.is_file()]
        for file in files:
            try:
                text = file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            register_text(text, source=source, meta={"path": str(file)})
            count += 1
    return {"registered_files": count, "db": str(DB_PATH)}


def selftest() -> None:
    global DATA_DIR, DB_PATH
    DATA_DIR = ROOT / "traces" / "provenance_registry_selftest"
    DB_PATH = DATA_DIR / "registry.sqlite"
    text = "AAPL calls look strong this week gamma favorable into close"
    register_text(text, "test_cloud")
    assert not check_provenance(text)["clean"]
    copied = "today note: AAPL calls look strong this week gamma favorable into close"
    assert not check_provenance(copied)["clean"]
    assert check_provenance("unrelated local note about UI layout")["clean"]


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("selftest")
    s = sub.add_parser("register")
    s.add_argument("--source", default="manual")
    s.add_argument("--file", dest="files", action="append", default=[])
    s.add_argument("path", nargs="*")
    s = sub.add_parser("backfill")
    s.add_argument("--source", default="external_backfill")
    s.add_argument("--file", dest="files", action="append", default=[])
    s.add_argument("path", nargs="*")
    s = sub.add_parser("check")
    s.add_argument("text")
    args = p.parse_args()
    if args.cmd == "selftest":
        selftest()
        print("PASS: provenance_registry selftest")
    elif args.cmd in {"register", "backfill"}:
        paths = list(args.path or []) + list(args.files or [])
        if not paths:
            raise SystemExit(f"{args.cmd} requires at least one path or --file")
        print(json.dumps(backfill_paths(paths, args.source), ensure_ascii=False, indent=2))
    elif args.cmd == "check":
        print(json.dumps(check_provenance(args.text), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
