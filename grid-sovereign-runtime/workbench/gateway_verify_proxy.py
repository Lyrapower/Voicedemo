"""8515 workbench → 8501 gateway proxy with server-side grid verification.

Browsers must not hold keyholder material; b11 uses this proxy on :8515 / ts.net /workbench/.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

WORKBENCH_DIR = Path(__file__).resolve().parent
GATEWAY_DIR = WORKBENCH_DIR.parent / "gateway"
if str(GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(GATEWAY_DIR))

from grid_verification_client import (  # noqa: E402
    attach_expanded_verification,
    attach_grid_verification,
)

DEFAULT_GATEWAY = os.environ.get("GRID_GATEWAY_BASE", "http://127.0.0.1:8501").rstrip("/")
DEFAULT_KEY_PATH = WORKBENCH_DIR.parent / ".grid_cleanroom" / "keyholder.key"
SIGNER_ID = "keyholder-v1"


def _ensure_key_env() -> None:
    if os.environ.get("GRID_KEYHOLDER_KEY", "").strip():
        return
    key_path = DEFAULT_KEY_PATH
    if not key_path.is_file():
        raise FileNotFoundError(f"keyholder key missing: {key_path}")
    os.environ["GRID_KEYHOLDER_KEY"] = str(key_path)


def _is_aster_model(model: Any) -> bool:
    m = str(model or "").strip()
    return m == "demo/aster" or m.endswith("/aster")


def _forward_post(path: str, body: dict[str, Any], *, timeout: float = 300.0) -> tuple[int, dict[str, Any]]:
    url = f"{DEFAULT_GATEWAY}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"error": raw[:400]}
        return exc.code, payload


def _inject_local_soul(payload: dict[str, Any]) -> dict[str, Any]:
    """HOME / grid-app:注入 local 魂组 read+recall(不动 local_gateway)。"""
    try:
        demo = WORKBENCH_DIR.parents[1]
        if str(demo) not in sys.path:
            sys.path.insert(0, str(demo))
        from grid_mem import DEFAULT_STORE_DB, inject_messages

        db = os.environ.get("GRID_STORE_DB") or DEFAULT_STORE_DB
        if not db or not os.path.isfile(db):
            return payload
        msgs = list(payload.get("messages") or [])
        q = ""
        for m in reversed(msgs):
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                q = m["content"]
                break
        # grid.html 传 grid-app;b11 HOME 传 b11-home;缺省按入口猜
        surface = str(payload.get("surface") or "").strip() or "grid-app"
        prefix = inject_messages(db, surface, q)
        if not prefix:
            return payload
        if msgs and msgs[0].get("role") == "system" and "[魂组近程]" in str(msgs[0].get("content") or ""):
            return payload
        out = dict(payload)
        out["messages"] = prefix + msgs
        return out
    except Exception:
        return payload


def proxy_chat_completions(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    _ensure_key_env()
    payload = dict(body or {})
    payload.pop("grid_verification", None)
    payload = _inject_local_soul(payload)
    if _is_aster_model(payload.get("model")):
        payload = attach_grid_verification(payload, gateway_base=DEFAULT_GATEWAY, signer_id=SIGNER_ID)
    return _forward_post("/v1/chat/completions", payload, timeout=float(payload.get("timeout") or 300.0))


def proxy_task_expanded(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    _ensure_key_env()
    payload = dict(body or {})
    payload.pop("grid_verification", None)
    task = str(payload.get("task") or "").strip()
    if not task:
        return 400, {"detail": "task required"}
    payload = attach_expanded_verification(
        payload,
        user_task=task,
        gateway_base=DEFAULT_GATEWAY,
        signer_id=SIGNER_ID,
    )
    return _forward_post("/task/expanded", payload)


def verification_probe() -> dict[str, Any]:
    try:
        _ensure_key_env()
        stub = {"model": "demo/aster", "messages": [{"role": "user", "content": "probe"}], "stream": False, "max_tokens": 8}
        attach_grid_verification(stub, gateway_base=DEFAULT_GATEWAY, signer_id=SIGNER_ID)
        return {"ok": True, "signer_id": SIGNER_ID, "gateway": DEFAULT_GATEWAY}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
