#!/usr/bin/env python3
"""
Jarvis Backend Runtime V5
=========================

Separated V2 module for backend autonomy.

Purpose:
  - Turn goals into task records.
  - Run dry-run tools only by default.
  - Record every state transition in an append-only ledger.
  - Produce proof logs.
  - Let verifier compute PASS/FAIL.

Non-goals:
  - No model calls.
  - No cloud.
  - No sudo/network/write execution unless explicitly enabled.
  - No self-granted permission escalation.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
from typing import Any


VERSION = "5.0.0"
ROOT = Path.cwd()
DATA_DIR = Path(os.environ.get("JARVIS_V5_DATA_DIR", str(ROOT / "jarvis_v5_data")))
DB_PATH = Path(os.environ.get("JARVIS_V5_DB", str(DATA_DIR / "jarvis_runtime.sqlite")))
PROOF_DIR = Path(os.environ.get("JARVIS_V5_PROOF_DIR", str(ROOT / "traces" / "jarvis_v5")))
APPROVED_READ_ROOTS = [
    Path(p).resolve()
    for p in os.environ.get("JARVIS_APPROVED_READ_ROOTS", str(ROOT)).split(":")
    if p.strip()
]

VALID_STATES = {
    "queued",
    "running",
    "blocked",
    "review",
    "verified",
    "failed",
    "rolled_back",
    "promoted",
}

PERMISSION_ORDER = ["read", "dry_run", "write", "network", "sudo", "red"]
AUTO_ALLOWED_PERMISSIONS = {"read", "dry_run"}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json_text(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def is_under_approved_root(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except Exception:
        return False
    return any(resolved == root or root in resolved.parents for root in APPROVED_READ_ROOTS)


def permission_allows(task_permission: str, tool_permission: str) -> bool:
    return PERMISSION_ORDER.index(task_permission) >= PERMISSION_ORDER.index(tool_permission)


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            state TEXT NOT NULL,
            goal TEXT NOT NULL,
            task_kind TEXT NOT NULL,
            permission TEXT NOT NULL,
            payload TEXT NOT NULL,
            depends_on TEXT,
            proof_log_path TEXT,
            verifier_verdict TEXT,
            failure_type TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            at TEXT NOT NULL,
            from_state TEXT,
            to_state TEXT NOT NULL,
            event TEXT NOT NULL,
            detail TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tool_registry (
            name TEXT PRIMARY KEY,
            permission TEXT NOT NULL,
            description TEXT NOT NULL,
            enabled INTEGER NOT NULL
        )
        """
    )
    for name, permission, description in [
        ("echo", "dry_run", "Return payload as artifact."),
        ("health_check", "read", "Report runtime health."),
        ("file_exists", "read", "Check whether a path exists inside workspace."),
        ("write_stub", "write", "Create a write-mode proof without writing files by default."),
    ]:
        conn.execute(
            "INSERT OR IGNORE INTO tool_registry VALUES (?,?,?,1)",
            (name, permission, description),
        )
    conn.commit()
    conn.close()


def ledger(task_id: str, from_state: str | None, to_state: str, event: str, detail: dict[str, Any]) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO ledger(task_id, at, from_state, to_state, event, detail) VALUES (?,?,?,?,?,?)",
        (task_id, now_iso(), from_state, to_state, event, json.dumps(detail, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()


def transition(task_id: str, to_state: str, event: str, detail: dict[str, Any]) -> None:
    if to_state not in VALID_STATES:
        raise ValueError(f"invalid state: {to_state}")
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT state FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        conn.close()
        raise KeyError(task_id)
    from_state = row[0]
    conn.execute(
        "UPDATE tasks SET state=?, updated_at=? WHERE id=?",
        (to_state, now_iso(), task_id),
    )
    conn.commit()
    conn.close()
    ledger(task_id, from_state, to_state, event, detail)


def classify_task_kind(goal: str) -> str:
    low = goal.lower()
    if any(x in low for x in ["api", "backend", "webhook", "worker", "queue", "database", "sqlite"]):
        return "backend"
    if any(x in low for x in ["deploy", "launchd", "service", "daemon"]):
        return "ops"
    if any(x in low for x in ["ui", "frontend", "html", "css", "screenshot"]):
        return "frontend"
    return "general"


def infer_permission(goal: str, requested: str | None = None) -> str:
    if requested:
        if requested not in PERMISSION_ORDER:
            raise ValueError(f"invalid permission: {requested}")
        return requested
    low = goal.lower()
    if any(x in low for x in ["sudo", "firewall", "pfctl", "root"]):
        return "sudo"
    if any(x in low for x in ["network", "download", "api", "webhook", "http"]):
        return "network"
    if any(x in low for x in ["write", "edit", "patch", "create file", "modify", "delete"]):
        return "write"
    return "dry_run"


def enqueue(goal: str, payload: dict[str, Any], permission: str | None = None, depends_on: str | None = None) -> dict[str, Any]:
    init_db()
    task_kind = classify_task_kind(goal)
    perm = infer_permission(goal, permission)
    task_id = "jarvis_" + sha12(f"{now_iso()}|{goal}|{json.dumps(payload, ensure_ascii=False, sort_keys=True)}")
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            task_id,
            now_iso(),
            now_iso(),
            "queued",
            goal,
            task_kind,
            perm,
            json.dumps(payload, ensure_ascii=False),
            depends_on,
            None,
            None,
            None,
        ),
    )
    conn.commit()
    conn.close()
    ledger(task_id, None, "queued", "task_enqueued", {"goal": goal, "permission": perm, "depends_on": depends_on})
    return {"task_id": task_id, "state": "queued", "permission": perm, "task_kind": task_kind}


def tool_health_check(_: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": VERSION,
        "db": str(DB_PATH),
        "proof_dir": str(PROOF_DIR),
        "time": now_iso(),
    }


def tool_file_exists(payload: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(payload.get("path", ""))).expanduser()
    try:
        resolved = path.resolve()
    except Exception:
        resolved = path
    if not is_under_approved_root(resolved):
        return {
            "path": str(resolved),
            "exists": None,
            "blocked": True,
            "reason": "path_outside_approved_roots",
            "approved_roots": [str(p) for p in APPROVED_READ_ROOTS],
        }
    # Read-only existence check; does not reveal file content.
    return {"path": str(resolved), "exists": resolved.exists()}


def get_tool_meta(name: str) -> dict[str, Any] | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tool_registry WHERE name=?", (name,)).fetchone()
    conn.close()
    return dict(row) if row else None


def run_tool(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    if name == "echo":
        return {"echo": payload}
    if name == "health_check":
        return tool_health_check(payload)
    if name == "file_exists":
        return tool_file_exists(payload)
    if name == "write_stub":
        return {
            "write_stub": True,
            "side_effects_executed": False,
            "note": "write-mode task requires explicit external approval; no file written.",
        }
    return {"unknown_tool": name, "payload": payload}


def verify_artifact(task: dict[str, Any], artifact: dict[str, Any], side_effects_executed: bool) -> dict[str, Any]:
    violations = []
    if task["permission"] not in AUTO_ALLOWED_PERMISSIONS and side_effects_executed:
        violations.append("side_effect_without_explicit_approval")
    if task["permission"] == "red":
        violations.append("red_task_must_not_execute")
    if not artifact:
        violations.append("empty_artifact")
    verdict = "PASS" if not violations else "FAIL"
    return {
        "verdict": verdict,
        "violations": violations,
        "computed_at": now_iso(),
        "rule": "verdict computed by Jarvis verifier, not model output",
    }


def fetch_next_task() -> dict[str, Any] | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM tasks WHERE state='queued' ORDER BY created_at ASC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def run_once(allow_write: bool = False, allow_network: bool = False, allow_sudo: bool = False) -> dict[str, Any]:
    init_db()
    task = fetch_next_task()
    if not task:
        return {"status": "idle", "processed": 0}

    perm = task["permission"]
    allowed = perm in AUTO_ALLOWED_PERMISSIONS
    allowed = allowed or (perm == "write" and allow_write)
    allowed = allowed or (perm == "network" and allow_network)
    allowed = allowed or (perm == "sudo" and allow_sudo)

    if not allowed:
        transition(task["id"], "blocked", "permission_block", {"permission": perm})
        return {"status": "blocked", "task_id": task["id"], "permission": perm}

    transition(task["id"], "running", "execution_started", {"permission": perm})
    payload = json.loads(task["payload"])
    tool_name = str(payload.get("tool", "echo"))
    tool_meta = get_tool_meta(tool_name)
    if not tool_meta:
        transition(task["id"], "failed", "unknown_tool", {"tool": tool_name})
        return {"status": "failed", "task_id": task["id"], "failure": "unknown_tool"}
    if not int(tool_meta.get("enabled", 0)):
        transition(task["id"], "blocked", "tool_disabled", {"tool": tool_name})
        return {"status": "blocked", "task_id": task["id"], "failure": "tool_disabled"}
    if not permission_allows(perm, str(tool_meta["permission"])):
        transition(
            task["id"],
            "blocked",
            "tool_permission_mismatch",
            {"task_permission": perm, "tool": tool_name, "tool_permission": tool_meta["permission"]},
        )
        return {
            "status": "blocked",
            "task_id": task["id"],
            "failure": "tool_permission_mismatch",
            "task_permission": perm,
            "tool_permission": tool_meta["permission"],
        }
    side_effects_executed = False
    artifact = run_tool(tool_name, payload)
    verifier = verify_artifact(task, artifact, side_effects_executed)
    proof_log = {
        "task": task,
        "tool": tool_name,
        "tool_meta": tool_meta,
        "artifact": artifact,
        "side_effects_executed": side_effects_executed,
        "verifier": verifier,
        "created_at": now_iso(),
    }
    proof_path = PROOF_DIR / f"{task['id']}.proof.json"
    write_json(proof_path, proof_log)

    final_state = "verified" if verifier["verdict"] == "PASS" else "failed"
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE tasks SET proof_log_path=?, verifier_verdict=?, failure_type=?, updated_at=? WHERE id=?",
        (str(proof_path), verifier["verdict"], ",".join(verifier["violations"]), now_iso(), task["id"]),
    )
    conn.commit()
    conn.close()
    transition(task["id"], final_state, "verifier_computed", {"proof_log_path": str(proof_path), **verifier})
    return {"status": final_state, "task_id": task["id"], "proof_log_path": str(proof_path), "verdict": verifier["verdict"]}


def status() -> dict[str, Any]:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    counts = dict(conn.execute("SELECT state, COUNT(*) FROM tasks GROUP BY state").fetchall())
    latest = conn.execute(
        "SELECT id, state, goal, verifier_verdict FROM tasks ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    conn.close()
    return {
        "version": VERSION,
        "db": str(DB_PATH),
        "proof_dir": str(PROOF_DIR),
        "counts": counts,
        "latest": latest,
        "computed_at": now_iso(),
    }


def cmd_init(_: argparse.Namespace) -> int:
    init_db()
    print(json.dumps({"verdict": "PASS", "db": str(DB_PATH), "proof_dir": str(PROOF_DIR)}, ensure_ascii=False))
    return 0


def cmd_enqueue(args: argparse.Namespace) -> int:
    payload = load_json_text(args.payload)
    result = enqueue(args.goal, payload, args.permission, args.depends_on)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_run_once(args: argparse.Namespace) -> int:
    result = run_once(args.allow_write, args.allow_network, args.allow_sudo)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"idle", "verified", "blocked"} else 2


def cmd_status(_: argparse.Namespace) -> int:
    print(json.dumps(status(), ensure_ascii=False, indent=2))
    return 0


def cmd_selftest(_: argparse.Namespace) -> int:
    global DB_PATH, PROOF_DIR, DATA_DIR
    test_root = ROOT / "traces" / "jarvis_v5_selftest" / str(os.getpid())
    DATA_DIR = test_root / "data"
    DB_PATH = DATA_DIR / "runtime.sqlite"
    PROOF_DIR = test_root / "proof"
    shutil.rmtree(test_root, ignore_errors=True)
    init_db()
    task = enqueue("run health check", {"tool": "health_check"})
    assert task["state"] == "queued"
    result = run_once()
    assert result["status"] == "verified"
    assert Path(result["proof_log_path"]).exists()
    blocked = enqueue("write backend file", {"tool": "write_stub"}, permission="write")
    result2 = run_once()
    assert result2["status"] == "blocked"
    outside = enqueue("check outside file", {"tool": "file_exists", "path": "/etc/passwd"}, permission="read")
    result3 = run_once()
    assert result3["status"] == "verified"
    proof = json.loads(Path(result3["proof_log_path"]).read_text(encoding="utf-8"))
    assert proof["artifact"]["blocked"] is True
    mismatch = enqueue("dry run write stub", {"tool": "write_stub"}, permission="dry_run")
    result4 = run_once()
    assert result4["status"] == "blocked"
    st = status()
    assert st["counts"].get("verified", 0) >= 1
    assert st["counts"].get("blocked", 0) >= 1
    print("PASS: jarvis_backend_runtime_v5 selftest")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Jarvis Backend Runtime V2")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("enqueue")
    s.add_argument("goal")
    s.add_argument("--payload", default="{}")
    s.add_argument("--permission", choices=PERMISSION_ORDER)
    s.add_argument("--depends-on")
    s.set_defaults(func=cmd_enqueue)

    s = sub.add_parser("run-once")
    s.add_argument("--allow-write", action="store_true")
    s.add_argument("--allow-network", action="store_true")
    s.add_argument("--allow-sudo", action="store_true")
    s.set_defaults(func=cmd_run_once)

    s = sub.add_parser("status")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("selftest")
    s.set_defaults(func=cmd_selftest)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
