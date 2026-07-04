"""FastAPI routes for Jarvis automation — mounted only on platform_main."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.jarvis.aether_readonly_adapter import load_aether_snapshot
from app.jarvis.proof_log import tail_proof_log
from app.jarvis.task_registry import JARVIS_ENTRY, JARVIS_HOST, JARVIS_PORT, list_tasks, run_task

router = APIRouter(prefix="/api/jarvis", tags=["jarvis-automation"])


@router.get("/entry")
async def jarvis_entry() -> dict[str, Any]:
    return {
        "entry_point": JARVIS_ENTRY,
        "host": JARVIS_HOST,
        "port": JARVIS_PORT,
        "sole_entry": True,
        "note": "All Jarvis automation tasks register here; sidecars remain read-only.",
    }


@router.get("/tasks")
async def jarvis_tasks() -> dict[str, Any]:
    return {"tasks": list_tasks(), "count": len(list_tasks())}


@router.post("/tasks/{task_id}/run")
async def jarvis_run_task(
    task_id: str,
    dry_run: bool = Query(default=True),
    force: bool = Query(default=False),
) -> dict[str, Any]:
    try:
        return run_task(task_id, dry_run=dry_run, force=force)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/aether/snapshot")
async def jarvis_aether_snapshot() -> dict[str, Any]:
    return load_aether_snapshot(write_artifact=True)


@router.get("/proof-log")
async def jarvis_proof_log(limit: int = Query(default=20, ge=1, le=200)) -> dict[str, Any]:
    rows = tail_proof_log(limit=limit)
    return {"entries": rows, "count": len(rows)}
