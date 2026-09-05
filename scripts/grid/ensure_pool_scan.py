#!/usr/bin/env python3
"""Run pool_daily_scan if pool_signals is missing/stale for today."""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AETHER = ROOT / "aether_nexus"
VENV_PY = AETHER / ".venv" / "bin" / "python"
sys.path.insert(0, str(AETHER))

from premarket_pool_context import pool_scan_fresh  # noqa: E402


def _emit(status: str, message: str) -> None:
    print(json.dumps({"status": status, "message": message}, ensure_ascii=False))


def main() -> int:
    today = dt.date.today()
    if pool_scan_fresh(today, max_age_minutes=150.0):
        _emit("skip", "pool_signals fresh")
        return 0

    py = VENV_PY if VENV_PY.is_file() else Path(sys.executable)
    proc = subprocess.run(
        [
            str(py),
            "-c",
            "from aether_dryrun import pool_daily_scan; pool_daily_scan()",
        ],
        cwd=str(AETHER),
        capture_output=True,
        text=True,
        timeout=900,
    )
    if proc.returncode != 0:
        _emit("error", (proc.stderr or proc.stdout or "pool_daily_scan failed")[:500])
        return proc.returncode

    if pool_scan_fresh(today, max_age_minutes=150.0):
        _emit("ok", "pool rescan complete")
        return 0
    _emit("warn", "pool rescan finished but signals still look stale")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
