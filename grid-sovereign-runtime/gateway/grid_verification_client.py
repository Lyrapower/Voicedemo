"""Shared Grid verification client — headless services (scheduler, factory).

Uses delegated service identity from env/file — NEVER browser localStorage.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib import request as urllib_request

GATEWAY_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = GATEWAY_DIR.parent
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from grid_chain_verification import (  # noqa: E402
    GRID_CHAIN_SCHEMA_VERSION,
    canonical_payload_hash,
)

DEFAULT_GATEWAY = os.environ.get("GRID_GATEWAY_BASE", "http://127.0.0.1:8501").rstrip("/")

SERVICE_SIGNER_ENV = {
    "keyholder-v1": "GRID_KEYHOLDER_KEY",
    "grid-scheduler-v1": "GRID_SCHEDULER_SIGNER_KEY",
    "alpha-factory-v1": "GRID_FACTORY_SIGNER_KEY",
}


def _load_service_key(signer_id: str) -> bytes:
    env_name = SERVICE_SIGNER_ENV.get(signer_id)
    if not env_name:
        raise ValueError(f"unknown service signer_id: {signer_id}")
    path = os.environ.get(env_name, "").strip()
    if not path:
        default = PROJECT_ROOT / ".grid_cleanroom" / "keyholder.key"
        path = str(default)
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"service signer key missing: {p} (set {env_name})")
    return p.read_bytes().strip()


def _post_json(url: str, body: dict, *, timeout: float = 30.0) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib_request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def sign_keyholder_challenge(gateway_base: str, *, signer_id: str) -> dict[str, Any]:
    import keyholder_challenge as kh

    key = _load_service_key(signer_id)
    ch = _post_json(f"{gateway_base.rstrip('/')}/challenge/new", {})
    response = kh.compute_response(ch["nonce"], float(ch["ts"]), key)
    return {"nonce": ch["nonce"], "ts": ch["ts"], "response": response}


def seal_trace_remote(gateway_base: str, *, chat_body: dict, route_id: str, payload_hash: str) -> dict:
    out = _post_json(
        f"{gateway_base.rstrip('/')}/grid/verification/trace-seal",
        {"route_id": route_id, "payload_hash": payload_hash, "chat_body": chat_body},
    )
    return out["trace"]


def build_grid_verification(
    chat_body: dict,
    *,
    gateway_base: str = DEFAULT_GATEWAY,
    signer_id: str,
    route_id: str | None = None,
) -> dict[str, Any]:
    """Return {grid_verification: ...} to merge into POST body."""
    if signer_id not in SERVICE_SIGNER_ENV:
        raise ValueError(f"unsupported signer_id: {signer_id}")
    rid = route_id or str(uuid.uuid4())
    ph = canonical_payload_hash(chat_body)
    trace = seal_trace_remote(gateway_base, chat_body=chat_body, route_id=rid, payload_hash=ph)
    kh = sign_keyholder_challenge(gateway_base, signer_id=signer_id)
    return {
        "grid_verification": {
            "schema_version": GRID_CHAIN_SCHEMA_VERSION,
            "route_id": rid,
            "signer_id": signer_id,
            "payload_hash": ph,
            "keyholder": kh,
            "trace": trace,
        }
    }


def attach_grid_verification(
    chat_body: dict,
    *,
    gateway_base: str = DEFAULT_GATEWAY,
    signer_id: str,
) -> dict[str, Any]:
    bundle = build_grid_verification(chat_body, gateway_base=gateway_base, signer_id=signer_id)
    return {**chat_body, **bundle}


def attach_expanded_verification(
    task_body: dict,
    *,
    user_task: str,
    gateway_base: str = DEFAULT_GATEWAY,
    signer_id: str,
) -> dict[str, Any]:
    """Merge model/messages + grid_verification so payload_hash matches POST body."""
    chat_stub = {
        "model": "demo/aster",
        "messages": [{"role": "user", "content": user_task}],
    }
    bundle = build_grid_verification(chat_stub, gateway_base=gateway_base, signer_id=signer_id)
    return {
        **task_body,
        "model": chat_stub["model"],
        "messages": chat_stub["messages"],
        **bundle,
    }


def attach_factory_verification(
    factory_body: dict,
    *,
    task_text: str,
    gateway_base: str = DEFAULT_GATEWAY,
    signer_id: str = "alpha-factory-v1",
) -> dict[str, Any]:
    chat_stub = {
        "model": "demo/aster",
        "messages": [{"role": "user", "content": task_text}],
    }
    bundle = build_grid_verification(chat_stub, gateway_base=gateway_base, signer_id=signer_id)
    return {
        **factory_body,
        "model": chat_stub["model"],
        "messages": chat_stub["messages"],
        **bundle,
    }
