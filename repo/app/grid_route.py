"""Aster /route — config/aster.toml + local_router.db only."""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from carriers.route_core import execute_route  # noqa: E402
from models.aster_config import channel_port  # noqa: E402

logger = logging.getLogger(__name__)
router = APIRouter(tags=["aster-route"])

LOG_DIR = _REPO_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)


class RouteRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=50000)
    explicit_layer: Optional[str] = None
    explicit_carrier: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, ge=1, le=8192)
    session_id: Optional[str] = None


class RouteResponse(BaseModel):
    audit_id: str
    timestamp: float
    invoked_carrier: Optional[str]
    target_layer: str
    contamination_detected: list
    intention_vector: Dict[str, float]
    response: str
    metadata: Dict[str, Any]


def _write_audit(record: Dict[str, Any]) -> None:
    log_file = LOG_DIR / f"router_audit_{time.strftime('%Y%m%d')}.jsonl"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


@router.post("/route", response_model=RouteResponse)
async def route_request(req: RouteRequest, request: Request):
    result = execute_route(
        prompt=req.prompt,
        explicit_layer=req.explicit_layer,
        explicit_carrier=req.explicit_carrier,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        session_id=req.session_id,
        mapper=request.app.state.mapper,
        loader=request.app.state.loader,
        anchor_loader=request.app.state.anchor_loader,
        memory_service=getattr(request.app.state, "memory", None),
    )

    if "error" in result and "response" not in result:
        _write_audit(
            {
                "audit_id": result.get("audit_id"),
                "timestamp": result.get("timestamp"),
                "status": "generation_failed",
                "error": result["error"],
                "compiled_intent": result.get("compiled_intent"),
                "port": channel_port(),
            }
        )
        raise HTTPException(status_code=502, detail=result["error"])

    _write_audit(
        {
            "audit_id": result["audit_id"],
            "timestamp": result["timestamp"],
            "status": "success",
            "raw_prompt": req.prompt,
            "compiled_intent": result.get("compiled_intent"),
            "response": result["response"],
            "metadata": result["metadata"],
            "port": 8787,
        }
    )

    return RouteResponse(
        audit_id=result["audit_id"],
        timestamp=result["timestamp"],
        invoked_carrier=result["invoked_carrier"],
        target_layer=result["target_layer"],
        contamination_detected=result["contamination_detected"],
        intention_vector=result["intention_vector"],
        response=result["response"],
        metadata=result["metadata"],
    )


@router.get("/substrates")
async def list_substrates(request: Request):
    return {"substrates": request.app.state.loader.list_substrates()}


@router.get("/carriers")
async def list_carriers():
    return {"carriers": []}


@router.get("/audit/{audit_id}")
async def get_audit(audit_id: str):
    today = time.strftime("%Y%m%d")
    log_file = LOG_DIR / f"router_audit_{today}.jsonl"
    if not log_file.exists():
        raise HTTPException(status_code=404, detail="No audit log for today")
    with open(log_file, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("audit_id") == audit_id:
                return record
    raise HTTPException(status_code=404, detail="Audit ID not found")
