"""Append-only proof log for Jarvis automation tasks."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG = ROOT / "logs" / "jarvis_tasks" / "proof_log.jsonl"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_proof(
    *,
    task_id: str,
    status: str,
    permission: str,
    dry_run: bool,
    detail: dict[str, Any] | None = None,
    artifacts: list[str] | None = None,
    log_path: Path | None = None,
) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    entry = {
        "run_id": run_id,
        "task_id": task_id,
        "ts": _utc_now(),
        "status": status,
        "permission": permission,
        "dry_run": dry_run,
        "artifacts": artifacts or [],
        "detail": detail or {},
    }
    path = log_path or DEFAULT_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    latest = path.parent / task_id / "latest.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return entry


def tail_proof_log(limit: int = 20, log_path: Path | None = None) -> list[dict[str, Any]]:
    path = log_path or DEFAULT_LOG
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
