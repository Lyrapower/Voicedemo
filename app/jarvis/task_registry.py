"""Central Jarvis task registry — sole automation scheduler surface."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

from app.jarvis.aether_readonly_adapter import load_aether_snapshot
from app.jarvis.proof_log import append_proof

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "jarvis_automation.yaml"
JARVIS_ENTRY = "app.platform_main:app"
JARVIS_HOST = "127.0.0.1"
JARVIS_PORT = 8686


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    title: str
    permission: str
    schedule: str
    enabled: bool
    allow_dry_run: bool
    handler: str
    artifacts: list[str]
    dry_run_only: bool = False


def _load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {"tasks": {}, "global": {}}
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}


def _parse_tasks(cfg: dict[str, Any]) -> dict[str, TaskSpec]:
    out: dict[str, TaskSpec] = {}
    for task_id, raw in (cfg.get("tasks") or {}).items():
        if not isinstance(raw, dict):
            continue
        out[task_id] = TaskSpec(
            task_id=task_id,
            title=str(raw.get("title", task_id)),
            permission=str(raw.get("permission", "read_only")),
            schedule=str(raw.get("schedule", "manual")),
            enabled=bool(raw.get("enabled", False)),
            allow_dry_run=bool(raw.get("allow_dry_run", True)),
            handler=str(raw.get("handler", "")),
            artifacts=[str(a) for a in (raw.get("artifacts") or [])],
            dry_run_only=bool(raw.get("dry_run_only", False)),
        )
    return out


def list_tasks() -> list[dict[str, Any]]:
    cfg = _load_config()
    tasks = _parse_tasks(cfg)
    return [
        {
            "task_id": spec.task_id,
            "title": spec.title,
            "permission": spec.permission,
            "schedule": spec.schedule,
            "enabled": spec.enabled,
            "allow_dry_run": spec.allow_dry_run,
            "dry_run_only": spec.dry_run_only,
            "handler": spec.handler,
            "artifacts": spec.artifacts,
            "entry_point": JARVIS_ENTRY,
        }
        for spec in tasks.values()
    ]


def _handler_aether_snapshot(*, dry_run: bool) -> dict[str, Any]:
    snap = load_aether_snapshot(write_artifact=True)
    return {"snapshot": snap, "artifact": "deliver/proof/jarvis/aether_snapshot_latest.json", "dry_run": dry_run}


def _handler_crypto_scan(*, dry_run: bool) -> dict[str, Any]:
    script = ROOT / "scripts" / "scan_crypto_rwa_public.py"
    if not script.exists():
        raise FileNotFoundError(f"missing scanner: {script}")
    cmd = [sys.executable, str(script)]
    if dry_run:
        cmd.append("--dry-run")
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, check=False)
    return {
        "exit_code": proc.returncode,
        "stdout_tail": proc.stdout.splitlines()[-8:],
        "stderr_tail": proc.stderr.splitlines()[-8:],
        "dry_run": dry_run,
    }


def _handler_trading_readiness(*, dry_run: bool) -> dict[str, Any]:
    from jarvis.trading_local_engine import run_daily_readiness_check

    if dry_run:
        return {
            "dry_run": True,
            "note": "Would run run_daily_readiness_check(); skipped in dry-run",
            "proof_path": "deliver/proof/trading/DAILY_READINESS_REPORT.md",
        }
    result = run_daily_readiness_check()
    return {"dry_run": False, "result": result}


def _handler_crypto_proof_compile(*, dry_run: bool) -> dict[str, Any]:
    from app.router.compiled_memory import build_compiled_memory

    target = ROOT / "knowledge" / "compiled" / "WORKSPACE_crypto.md"
    if dry_run:
        return {
            "dry_run": True,
            "would_write": str(target.relative_to(ROOT)),
            "note": "compile skipped in dry-run",
        }
    build_compiled_memory()
    return {"dry_run": False, "written": str(target.relative_to(ROOT)), "exists": target.exists()}


_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "aether_snapshot": _handler_aether_snapshot,
    "crypto_scan": _handler_crypto_scan,
    "trading_readiness": _handler_trading_readiness,
    "crypto_proof_compile": _handler_crypto_proof_compile,
}


def run_task(task_id: str, *, dry_run: bool | None = None, force: bool = False) -> dict[str, Any]:
    cfg = _load_config()
    global_cfg = cfg.get("global") or {}
    tasks = _parse_tasks(cfg)
    if task_id not in tasks:
        raise KeyError(f"unknown task_id: {task_id}")
    spec = tasks[task_id]
    if dry_run is None:
        dry_run = bool(global_cfg.get("dry_run_default", True))
    if spec.dry_run_only:
        dry_run = True
    if not spec.enabled and not force:
        entry = append_proof(
            task_id=task_id,
            status="SKIPPED",
            permission=spec.permission,
            dry_run=dry_run,
            detail={"reason": "task disabled in config/jarvis_automation.yaml"},
            artifacts=spec.artifacts,
        )
        return {"ok": False, "task_id": task_id, "proof": entry}
    if dry_run and not spec.allow_dry_run:
        entry = append_proof(
            task_id=task_id,
            status="BLOCKED",
            permission=spec.permission,
            dry_run=True,
            detail={"reason": "dry_run not allowed for this task"},
            artifacts=spec.artifacts,
        )
        return {"ok": False, "task_id": task_id, "proof": entry}
    if spec.permission in {"broker", "wallet", "execution"}:
        entry = append_proof(
            task_id=task_id,
            status="BLOCKED",
            permission=spec.permission,
            dry_run=dry_run,
            detail={"reason": "forbidden permission level"},
            artifacts=spec.artifacts,
        )
        return {"ok": False, "task_id": task_id, "proof": entry}

    handler = _HANDLERS.get(spec.handler)
    if handler is None:
        raise RuntimeError(f"no handler registered for {spec.handler}")

    append_proof(
        task_id=task_id,
        status="STARTED",
        permission=spec.permission,
        dry_run=dry_run,
        detail={"handler": spec.handler},
        artifacts=spec.artifacts,
    )
    try:
        detail = handler(dry_run=dry_run)
        ok = True
        if spec.handler == "crypto_scan":
            ok = int(detail.get("exit_code", 1)) == 0
        status = "PASS" if ok else "FAIL"
        entry = append_proof(
            task_id=task_id,
            status=status,
            permission=spec.permission,
            dry_run=dry_run,
            detail=detail,
            artifacts=spec.artifacts,
        )
        return {"ok": ok, "task_id": task_id, "dry_run": dry_run, "proof": entry, "detail": detail}
    except Exception as exc:
        entry = append_proof(
            task_id=task_id,
            status="FAIL",
            permission=spec.permission,
            dry_run=dry_run,
            detail={"error": str(exc)},
            artifacts=spec.artifacts,
        )
        return {"ok": False, "task_id": task_id, "proof": entry, "error": str(exc)}
