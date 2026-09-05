#!/usr/bin/env python3
"""
Fleet Status Exporter
=====================

Reads the real ledgers, computes clean-days per daemon, writes
fleet_status.json for daemon_dashboard.html.

clean days = consecutive days, counting back from today, with ZERO
stop-condition events for that daemon in the ledger. One stop event
resets the streak — trust is rebuilt from the day after the last incident.
A daemon with no ledger rows at all has 0 clean days (unproven ≠ clean).

Sources (both optional; exporter degrades gracefully):
  - sentinel ledger  events table   (kind LIKE 'stop%' / 'halt%' / alarm)
  - jarvis ledger    to_state='blocked' transitions
  - heartbeat rows   (kind='heartbeat' or any row that day) prove the daemon
    was actually alive that day; days with no rows at all do not count
    toward the streak unless ALLOW_SILENT_DAYS=1.

Registry: daemons.json declares the fleet (names, kinds, manual statuses).
Ledger only ever *lowers* what the registry claims — it can add stop events
and cap clean days; it cannot promote a frozen daemon to running. Manual
freeze/lock always wins over ledger data.

Usage:
  python3 fleet_status_exporter.py                    # write fleet_status.json
  python3 fleet_status_exporter.py --print            # stdout only
  python3 fleet_status_exporter.py --selftest         # synthetic-ledger test
  python3 fleet_status_exporter.py --init-registry    # write starter daemons.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path.cwd()
SENTINEL_DB = Path(os.environ.get("SENTINEL_V5_DB", str(ROOT / "sentinel_v5_data" / "sentinel_ledger.sqlite")))
JARVIS_DB = Path(os.environ.get("JARVIS_V5_DB", str(ROOT / "jarvis_v5_data" / "jarvis_runtime.sqlite")))
GRID_STORE_DB = Path(os.environ.get(
    "GRID_STORE_DB",
    str(ROOT.parent / "grid-sovereign-runtime" / "data" / "grid_store.db"),
))
TRACE_DAEMON_DIR = Path(os.environ.get(
    "TRACE_DAEMON_DIR",
    str(ROOT.parent / "grid-sovereign-runtime" / "traces" / "daemon"),
))
REGISTRY_PATH = Path(os.environ.get("FLEET_REGISTRY", str(ROOT / "daemons.json")))
OUT_PATH = Path(os.environ.get("FLEET_STATUS_OUT", str(ROOT / "fleet_status.json")))
ALLOW_SILENT_DAYS = os.environ.get("ALLOW_SILENT_DAYS", "0") == "1"
MAX_LOOKBACK_DAYS = int(os.environ.get("FLEET_LOOKBACK_DAYS", "365"))

STOP_KINDS = ("stop", "halt", "alarm", "guard_alarm", "signature_verification_failed",
              "ledger_write_failed", "scope_out_of_bounds", "lyra_manual_intervention")

DEFAULT_GATES = [7, 30]

STARTER_REGISTRY = {
    "daemons": [
        {"id": "post_market",    "name": "Post-market",    "kind": "report-only",       "status": "running"},
        {"id": "research",       "name": "Research",       "kind": "report-only",       "status": "running"},
        {"id": "trading_screen", "name": "Trading Screen", "kind": "report-only",       "status": "running"},
        {"id": "ocr",            "name": "OCR",            "kind": "read · multimodal", "status": "running"},
        {"id": "build",          "name": "Build",          "kind": "in trust window",   "status": "building"},
        {"id": "deploy",         "name": "Deploy",         "kind": "write · gated",     "status": "frozen"},
        {"id": "cc_cli",         "name": "CC CLI",         "kind": "EXECUTION_FROZEN=1","status": "locked"},
    ],
    "_note": "status is the manual override; ledger can lower, never promote. "
             "Optional per-daemon: \"gates\": [30, 90] overrides the default trust "
             "ladder — higher-stakes daemons get longer gates (e.g. anything "
             "touching people or client money). Optional: \"project\": \"aether\" "
             "for grouping when the fleet grows."
}


def today_utc() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        raise SystemExit(f"registry not found: {REGISTRY_PATH} (run --init-registry first)")
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _rows(db: Path, sql: str, params: tuple = ()) -> list:
    if not db.exists():
        return []
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []  # table absent in this deployment — fine, degrade
    finally:
        conn.close()


def daemon_day_sets(daemon_id: str) -> tuple[set[dt.date], set[dt.date]]:
    """Return (active_days, stop_days) for a daemon across both ledgers.
    A row belongs to a daemon when its detail/subject/task_id mentions the id."""
    active: set[dt.date] = set()
    stops: set[dt.date] = set()
    needle = daemon_id.lower()

    # sentinel events: (ts, kind, detail)
    for ts, kind, detail in _rows(SENTINEL_DB, "SELECT ts, kind, detail FROM events"):
        blob = f"{kind} {detail}".lower()
        if needle not in blob:
            continue
        day = dt.date.fromisoformat(str(ts)[:10])
        active.add(day)
        if any(k in str(kind).lower() for k in STOP_KINDS):
            stops.add(day)

    # jarvis ledger: (task_id, at, to_state, event, detail)
    for task_id, at, to_state, event, detail in _rows(
        JARVIS_DB, "SELECT task_id, at, to_state, event, detail FROM ledger"
    ):
        blob = f"{task_id} {event} {detail}".lower()
        if needle not in blob:
            continue
        day = dt.date.fromisoformat(str(at)[:10])
        active.add(day)
        if str(to_state) == "blocked" or any(k in str(event).lower() for k in STOP_KINDS):
            stops.add(day)

    # grid_store events: (source, kind, payload, ts)
    for source, kind, payload, ts in _rows(
        GRID_STORE_DB, "SELECT source, kind, payload, ts FROM events"
    ):
        blob = f"{source} {kind} {payload}".lower()
        if needle not in blob:
            continue
        day = dt.datetime.fromtimestamp(float(ts), dt.timezone.utc).date()
        active.add(day)
        if any(k in str(kind).lower() for k in STOP_KINDS):
            stops.add(day)

    return active, stops


def _trace_trust_credit(trace: dict) -> bool:
    if trace.get("dry_run"):
        return False
    if trace.get("rehearsal"):
        return False
    if trace.get("telegram_tier") == "red":
        return False
    if (trace.get("final") or {}).get("data_suspect"):
        return False
    return bool(trace.get("trust_credit"))


def post_market_trust_days() -> tuple[int, str | None]:
    """Trust ladder from daemon traces — only production-quality runs count."""
    if not TRACE_DAEMON_DIR.is_dir():
        return 0, None
    by_day: dict[dt.date, dict] = {}
    for path in TRACE_DAEMON_DIR.glob("summary_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        try:
            day = dt.date.fromisoformat(str(data.get("trade_date")))
        except ValueError:
            continue
        prev = by_day.get(day)
        if not prev or str(data.get("generated_at") or "") > str(prev.get("generated_at") or ""):
            by_day[day] = data

    last_stop: str | None = None
    streak = 0
    day = today_utc()
    for _ in range(MAX_LOOKBACK_DAYS):
        trace = by_day.get(day)
        if trace is None:
            break
        if _trace_trust_credit(trace):
            streak += 1
        else:
            last_stop = day.isoformat()
            break
        day -= dt.timedelta(days=1)
    return streak, last_stop


def clean_days(daemon_id: str) -> tuple[int, str | None]:
    """Consecutive clean days ending today. Returns (streak, last_stop_iso)."""
    if daemon_id == "post_market":
        return post_market_trust_days()
    active, stops = daemon_day_sets(daemon_id)
    last_stop = max(stops).isoformat() if stops else None
    streak = 0
    day = today_utc()
    for _ in range(MAX_LOOKBACK_DAYS):
        if day in stops:
            break
        if day in active or ALLOW_SILENT_DAYS:
            if day in active or streak > 0 or ALLOW_SILENT_DAYS:
                streak += 1 if (day in active or ALLOW_SILENT_DAYS) else 0
        else:
            # silent day with no heartbeat: streak cannot grow through it
            break
        day -= dt.timedelta(days=1)
    return streak, last_stop


def build_status() -> dict:
    reg = load_registry()
    out = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "gates": DEFAULT_GATES, "daemons": []}
    for d in reg["daemons"]:
        row = {"name": d["name"], "kind": d.get("kind", ""), "status": d["status"]}
        gates = d.get("gates", DEFAULT_GATES)
        if list(gates) != DEFAULT_GATES:
            row["gates"] = list(gates)          # per-daemon trust ladder override
        if d.get("project"):
            row["project"] = d["project"]
        if d["status"] in ("running", "building"):
            streak, last_stop = clean_days(d["id"])
            row["days"] = streak
            if last_stop:
                row["last_stop"] = last_stop
            # ledger can only lower: a running daemon with a stop TODAY shows blocked
            _, stops = daemon_day_sets(d["id"])
            if today_utc() in stops:
                row["status"] = "building"   # demoted pending Lyra review
                row["kind"] = (row["kind"] + " · stop today").strip(" ·")
        out["daemons"].append(row)
    return out


def selftest() -> None:
    """Synthetic ledgers in a temp dir; verify streak logic end to end."""
    global SENTINEL_DB, JARVIS_DB, REGISTRY_PATH
    tmp = Path(tempfile.mkdtemp())
    SENTINEL_DB = tmp / "sentinel.sqlite"
    JARVIS_DB = tmp / "jarvis.sqlite"
    REGISTRY_PATH = tmp / "daemons.json"
    REGISTRY_PATH.write_text(json.dumps({"daemons": [
        {"id": "alpha", "name": "Alpha", "kind": "report-only", "status": "running"},
        {"id": "beta",  "name": "Beta",  "kind": "report-only", "status": "running"},
        {"id": "gamma", "name": "Gamma", "kind": "write",       "status": "frozen"},
        {"id": "delta", "name": "Delta", "kind": "people-facing", "status": "running",
         "gates": [30, 90], "project": "openclaw"},
    ]}), encoding="utf-8")

    conn = sqlite3.connect(SENTINEL_DB)
    conn.execute("CREATE TABLE events(ts TEXT, kind TEXT, detail TEXT)")
    today = today_utc()
    # alpha: heartbeats for 10 straight days, no stops -> streak 10
    for i in range(10):
        conn.execute("INSERT INTO events VALUES (?,?,?)",
                     ((today - dt.timedelta(days=i)).isoformat() + "T12:00:00",
                      "heartbeat", "daemon=alpha ok"))
    # beta: heartbeats 10 days but a stop 3 days ago -> streak 3
    for i in range(10):
        conn.execute("INSERT INTO events VALUES (?,?,?)",
                     ((today - dt.timedelta(days=i)).isoformat() + "T12:00:00",
                      "heartbeat", "daemon=beta ok"))
    conn.execute("INSERT INTO events VALUES (?,?,?)",
                 ((today - dt.timedelta(days=3)).isoformat() + "T09:00:00",
                  "guard_alarm", "daemon=beta scope_out_of_bounds"))
    conn.commit(); conn.close()

    status = build_status()
    by = {d["name"]: d for d in status["daemons"]}
    assert by["Alpha"]["days"] == 10, by["Alpha"]
    assert by["Beta"]["days"] == 3, by["Beta"]
    assert by["Beta"]["last_stop"] == (today - dt.timedelta(days=3)).isoformat()
    assert "days" not in by["Gamma"] and by["Gamma"]["status"] == "frozen"
    # frozen stays frozen even though ledger is silent about it (no promotion)
    assert by["Delta"]["gates"] == [30, 90], by["Delta"]     # per-daemon ladder
    assert by["Delta"]["project"] == "openclaw"
    assert "gates" not in by["Alpha"]                        # default ladder omitted
    print("PASS: fleet_status_exporter selftest")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--init-registry", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        selftest(); return 0
    if args.init_registry:
        if REGISTRY_PATH.exists():
            raise SystemExit(f"refusing to overwrite existing {REGISTRY_PATH}")
        REGISTRY_PATH.write_text(json.dumps(STARTER_REGISTRY, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        print(f"wrote {REGISTRY_PATH}"); return 0

    status = build_status()
    text = json.dumps(status, ensure_ascii=False, indent=2)
    if args.print:
        print(text); return 0
    OUT_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {OUT_PATH} ({len(status['daemons'])} daemons)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
