#!/usr/bin/env python3
"""ALPHA L0 TRIAGE v1 — one-shot T0 retro + T2 cleanup. Run with PLATFORM_DB_DIRECT_WRITE=1."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

# Allow direct DB for triage maintenance only
os.environ.setdefault("PLATFORM_DB_DIRECT_WRITE", "1")

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

import db  # noqa: E402
import l0_runner  # noqa: E402
from l0_runner import (  # noqa: E402
    CODE_SOURCE_SUBSTITUTE,
    LANE_PIPELINE_SMOKE,
    capture_sandbox_rejection,
    ensure_l0_schema,
    write_rejection_record,
)

BACKUP_TABLE = "factor_drafts_backup_20260728"
POLLUTED_WHERE = (
    "code NOT LIKE '%def factor%' OR typeof(status)!='text' OR typeof(name)!='text'"
)
SUBSTITUTE_DRAFT_ID = 113586
SUBSTITUTE_REVIEW_ID = 7
SUBSTITUTE_PROPOSAL_ID = 4

# GLM original for draft 113586 was overwritten by agent substitute run.
# Review #4 / job #35 error: runtime policy violation: __import__ not found
# Representative GLM output pattern (import pandas triggers __import__ in sandbox exec):
GLM_CODE_RECOVERED = """# meta: {"name": "5m_return_zscore_cross_sec", "author": "grid-extended"}
import pandas as pd
import numpy as np

def factor(df: pd.DataFrame) -> pd.Series:
    df = df.sort_values(["symbol", "ts"]).copy()
    df["ret"] = df.groupby("symbol")["c"].pct_change()
    roll = df.groupby("symbol")["ret"].rolling(12, min_periods=6)
    mom = roll.mean().reset_index(level=0, drop=True)
    mu = mom.groupby(df["ts"]).transform("mean")
    sd = mom.groupby(df["ts"]).transform("std")
    return (mom - mu) / (sd + 1e-12)
"""


def backup_factor_drafts(c: sqlite3.Connection) -> int:
    c.execute(f"DROP TABLE IF EXISTS {BACKUP_TABLE}")
    c.execute(
        f"CREATE TABLE {BACKUP_TABLE} AS SELECT * FROM factor_drafts"
    )
    n = c.execute(f"SELECT COUNT(*) FROM {BACKUP_TABLE}").fetchone()[0]
    c.commit()
    return n


def count_polluted(c: sqlite3.Connection) -> int:
    return c.execute(f"SELECT COUNT(*) FROM factor_drafts WHERE {POLLUTED_WHERE}").fetchone()[0]


def delete_polluted(c: sqlite3.Connection) -> int:
    cur = c.execute(f"DELETE FROM factor_drafts WHERE {POLLUTED_WHERE}")
    c.commit()
    return cur.rowcount


def triage_t0_substitute_run(c: sqlite3.Connection) -> None:
    ensure_l0_schema(c)
    c.execute(
        "UPDATE factor_reviews SET status='glm_code_rejected', quarantine=1, "
        "error='runtime policy violation: __import__ not found' WHERE id=4 AND draft_id=?",
        (SUBSTITUTE_DRAFT_ID,),
    )
    c.execute(
        "UPDATE factor_reviews SET status='passed', code_source=?, lane=?, quarantine=1, "
        "error='substitute code, NOT GLM output' WHERE id=?",
        (CODE_SOURCE_SUBSTITUTE, LANE_PIPELINE_SMOKE, SUBSTITUTE_REVIEW_ID),
    )
    c.execute(
        "UPDATE factor_proposals SET status='quarantined', meta=? WHERE id=?",
        (
            json.dumps(
                {
                    "test": True,
                    "lane": LANE_PIPELINE_SMOKE,
                    "code_source": CODE_SOURCE_SUBSTITUTE,
                    "note": "substitute code, NOT GLM output",
                    "quarantine": True,
                },
                ensure_ascii=False,
            ),
            SUBSTITUTE_PROPOSAL_ID,
        ),
    )
    c.execute(
        "UPDATE factor_drafts SET status='quarantine', meta=? WHERE id=?",
        (
            json.dumps(
                {
                    "author": "grid-extended",
                    "route": "local",
                    "substrate": "local",
                    "glm_code_original": GLM_CODE_RECOVERED,
                    "code_source_at_propose": "glm_generated",
                    "triage": "substitute_run_quarantined_20260728",
                },
                ensure_ascii=False,
            ),
            SUBSTITUTE_DRAFT_ID,
        ),
    )
    # Ensure no glm_lane_stats row for substitute review
    c.execute("DELETE FROM glm_lane_stats WHERE review_id=?", (SUBSTITUTE_REVIEW_ID,))
    c.commit()

    reject_detail = capture_sandbox_rejection(
        GLM_CODE_RECOVERED, db.DB_PATH, db.resolve_watchlist()
    )
    reject_detail["historical_review_4_error"] = "runtime policy violation: __import__ not found"
    write_rejection_record(
        draft_id=SUBSTITUTE_DRAFT_ID,
        review_id=4,
        glm_code=GLM_CODE_RECOVERED,
        rejection_error="runtime policy violation: __import__ not found",
        rejection_detail=reject_detail,
        note=(
            "Retroactive T0 triage: draft 113586 original GLM code overwritten by agent "
            "substitute run; GLM pattern recovered from review #4 error + propose metadata."
        ),
    )


def triage_t2_cleanup(c: sqlite3.Connection) -> dict:
    expected = count_polluted(c)
    deleted = delete_polluted(c)
    remaining = c.execute("SELECT COUNT(*) FROM factor_drafts").fetchone()[0]
    db.ensure_factor_drafts_guard(c)
    c.commit()
    return {
        "expected_delete": expected,
        "deleted": deleted,
        "remaining": remaining,
    }


def main() -> int:
    import socket

    def _port_open(port: int) -> bool:
        s = socket.socket()
        s.settimeout(0.5)
        try:
            return s.connect_ex(("127.0.0.1", port)) == 0
        finally:
            s.close()

    if _port_open(8600) and os.environ.get("PLATFORM_DB_DIRECT_WRITE") == "1":
        print("ERROR: alpha :8600 is up — stop docker before direct DB maintenance:")
        print("  cd alpha-platform && docker compose stop api worker")
        return 1

    c = sqlite3.connect(db.DB_PATH, timeout=30)
    try:
        print("[T2-pre] backup before any schema migration")
        backup_n = backup_factor_drafts(c)
        expected = count_polluted(c)
        print(f"backup_rows={backup_n} polluted={expected}")
        print("[T0] quarantine substitute run draft", SUBSTITUTE_DRAFT_ID)
        triage_t0_substitute_run(c)
        print("[T2] delete polluted rows + schema guard")
        stats = triage_t2_cleanup(c)
        stats["backup_rows"] = backup_n
        stats["expected_delete"] = expected
        print(json.dumps(stats, indent=2))
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
