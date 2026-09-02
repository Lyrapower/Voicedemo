"""Alpha Factory · Grid L1 client — single downstream interface to 8501 /factory/task.

Workshop code must not name models or cloud endpoints; only this module talks to Grid.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx

# FMP key 不进 INFO 日志(httpx INFO 会把含 apikey= 的 URL 整行打出;2026-09-02 砥 P0)
import logging
logging.getLogger("httpx").setLevel(logging.WARNING)

GRID_GATEWAY_URL = (os.getenv("GRID_GATEWAY_URL") or "http://127.0.0.1:8501").rstrip("/")
FACTORY_TIMEOUT = float(os.getenv("FACTORY_TASK_TIMEOUT", "360"))


def _ensure_gw_pkg() -> None:
    candidates: list[Path] = []
    env_pkg = os.getenv("GRID_GATEWAY_PKG", "").strip()
    if env_pkg:
        candidates.append(Path(env_pkg))
    scripts_pkg = os.getenv("GRID_SCRIPTS_PKG", "").strip()
    if scripts_pkg:
        sp = Path(scripts_pkg)
        if sp.is_dir() and str(sp) not in sys.path:
            sys.path.insert(0, str(sp))
    here = Path(__file__).resolve()
    if len(here.parents) >= 3:
        root = here.parents[2]
        candidates.append(root / "grid-sovereign-runtime" / "gateway")
        scripts = root / "grid-sovereign-runtime" / "scripts"
        if scripts.is_dir() and str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
    candidates.append(here.parent / "vendor" / "gateway")
    for p in candidates:
        if p.is_dir() and str(p) not in sys.path:
            sys.path.insert(0, str(p))
            return


def factory_task(
    kind: str,
    payload: dict[str, Any],
    *,
    budget_hint: str = "std",
    trace_id: str | None = None,
) -> dict[str, Any]:
    from factory_prompts import build_factory_task

    _ensure_gw_pkg()
    from grid_verification_client import attach_factory_verification

    task_text = build_factory_task(kind, payload, budget_hint)
    body = {
        "kind": kind,
        "payload": payload,
        "budget_hint": budget_hint,
        "trace_id": trace_id or str(uuid.uuid4()),
        "mission_ref": {"source": "alpha_factory"},
    }
    body = attach_factory_verification(
        body,
        task_text=task_text,
        gateway_base=GRID_GATEWAY_URL,
        signer_id="alpha-factory-v1",
    )
    url = f"{GRID_GATEWAY_URL}/factory/task"
    with httpx.Client(timeout=FACTORY_TIMEOUT) as client:
        r = client.post(url, json=body)
    if r.status_code == 429:
        raise FactoryGridError("Grid 推理槽满 · 8501 正在跑别的任务 · 等 30s 再点")
    if r.status_code >= 400:
        raise FactoryGridError(f"Grid factory HTTP {r.status_code}: {r.text[:400]}")
    data = r.json()
    if not data.get("ok"):
        raise FactoryGridError(str(data.get("error") or data.get("detail") or "factory task failed"))
    return data


class FactoryGridError(Exception):
    pass
