"""Additive routes for Grid verification — trace seal only; no Aster inference."""
from __future__ import annotations

import hashlib
import json
import secrets
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

GATEWAY_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = GATEWAY_DIR.parent
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from grid_chain_verification import (  # noqa: E402
    GRID_CHAIN_SCHEMA_VERSION,
    canonical_payload_hash,
    register_route_id,
)


def _seal_trace(*, raw_text: str, route_id: str, channel: str = "grid-verification") -> dict[str, Any]:
    import cleanroom as _cr

    key = _cr.ensure_init()
    raw_sha = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    trace_id = "grd_" + secrets.token_hex(8)
    trace = {
        "kind": "GRID_TRACE",
        "trace_id": trace_id,
        "created_at": _cr.now_iso(),
        "channel": channel,
        "privacy": "GREEN",
        "raw_sha256": raw_sha,
        "raw_text": raw_text,
        "notes": f"route_id={route_id}",
        "route_id": route_id,
        "schema_version": GRID_CHAIN_SCHEMA_VERSION,
    }
    sig = _cr.sign_payload(trace, key)
    trace["signature"] = sig
    trace["watermark"] = f"GRID_TRACE::{trace_id}::{sig[:16]}"
    return trace


def build_grid_verification_router() -> APIRouter:
    r = APIRouter(prefix="/grid/verification", tags=["grid-verification"])

    @r.get("/schema")
    async def schema():
        return {"schema_version": GRID_CHAIN_SCHEMA_VERSION}

    @r.post("/trace-seal")
    async def trace_seal(body: dict):
        route_id = str(body.get("route_id") or "").strip()
        payload_hash = str(body.get("payload_hash") or "").strip()
        chat_body = body.get("chat_body")
        if not isinstance(chat_body, dict):
            raise HTTPException(422, "chat_body object required")
        if not route_id or not payload_hash:
            raise HTTPException(422, "route_id and payload_hash required")
        expected = canonical_payload_hash(chat_body)
        if payload_hash != expected:
            raise HTTPException(422, f"payload_hash mismatch (expected {expected[:12]}…)")
        if not register_route_id(route_id, stage="trace-seal"):
            raise HTTPException(409, "route_id replay rejected")
        raw_text = json.dumps(
            {"route_id": route_id, "payload_hash": payload_hash, "model": chat_body.get("model")},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        trace = _seal_trace(raw_text=raw_text, route_id=route_id)
        return {
            "schema_version": GRID_CHAIN_SCHEMA_VERSION,
            "route_id": route_id,
            "payload_hash": payload_hash,
            "trace": trace,
            "sealed_at": time.time(),
        }

    return r
