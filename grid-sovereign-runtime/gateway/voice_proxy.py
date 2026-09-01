"""WS /voice proxy + POST /voice/telemetry — isolated from inference chain."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from voice_gate import audit_failure, is_locked, record_failure, record_success

logger = logging.getLogger("voice_proxy")


def build_voice_router(
    *,
    project_root: Path,
    daemon_port: int = 8504,
    kh_verify: Callable[..., dict[str, Any]] | None = None,
    kh_available: bool = False,
    require_keyholder: bool = False,
) -> APIRouter:
    router = APIRouter()
    gate_audit = project_root / "data" / "voice_gate_audit.jsonl"
    telemetry_log = project_root / "data" / "voice_telemetry.jsonl"
    upstream_url = f"ws://127.0.0.1:{int(daemon_port)}/ws/voice"

    def _peer(ws: WebSocket) -> str:
        if ws.client:
            return (ws.client.host or "unknown").split("%")[0]
        return "unknown"

    async def _send_error(ws: WebSocket, *, code: str, detail: str) -> None:
        try:
            await ws.send_json({"type": "error", "code": code, "detail": detail})
        except Exception:
            pass

    async def _deny(
        ws: WebSocket,
        *,
        host: str | None,
        code: str,
        detail: str,
    ) -> None:
        row = record_failure(host, code=code, detail=detail)
        audit_failure(gate_audit, row)
        await _send_error(ws, code=code, detail=detail)
        with contextlib.suppress(Exception):
            await ws.close(code=1008, reason=code)

    def _verify_keyholder(kh: dict | None) -> tuple[bool, str]:
        if not require_keyholder:
            return True, ""
        if not kh_available or kh_verify is None:
            return False, "keyholder module unavailable"
        if not kh or not isinstance(kh, dict):
            return False, "keyholder credentials required"
        nonce = kh.get("nonce")
        ts = kh.get("ts")
        response = kh.get("response")
        if not (nonce and ts is not None and response):
            return False, "keyholder nonce/ts/response required"
        result = kh_verify(nonce, float(ts), str(response))
        if result.get("verified"):
            return True, ""
        return False, str(result.get("reason") or "keyholder verification failed")

    @router.websocket("/voice")
    async def voice_ws(client_ws: WebSocket) -> None:
        host = _peer(client_ws)
        locked, _until = is_locked(host)
        await client_ws.accept()
        if locked:
            await _deny(
                client_ws,
                host=host,
                code="keyholder_locked",
                detail="too many failures; retry later",
            )
            return

        try:
            first = await asyncio.wait_for(client_ws.receive(), timeout=12.0)
        except asyncio.TimeoutError:
            with contextlib.suppress(Exception):
                await client_ws.close(code=1008, reason="init_timeout")
            return

        if first.get("type") == "websocket.disconnect":
            return

        text = first.get("text")
        if not text:
            await _deny(
                client_ws,
                host=host,
                code="keyholder_denied",
                detail="session.init required",
            )
            return

        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            await _deny(
                client_ws,
                host=host,
                code="keyholder_denied",
                detail="invalid session.init json",
            )
            return

        if obj.get("type") != "session.init":
            await _deny(
                client_ws,
                host=host,
                code="keyholder_denied",
                detail="session.init required first",
            )
            return

        ok, reason = _verify_keyholder(obj.get("keyholder"))
        if not ok:
            await _deny(client_ws, host=host, code="keyholder_denied", detail=reason)
            return

        record_success(host)

        try:
            import websockets
        except ImportError:
            await _deny(
                client_ws,
                host=host,
                code="voice_unavailable",
                detail="websockets package missing",
            )
            return

        try:
            async with websockets.connect(upstream_url, open_timeout=5, max_size=None) as upstream:
                await upstream.send(text)

                async def upstream_to_client() -> None:
                    try:
                        async for message in upstream:
                            if isinstance(message, str):
                                await client_ws.send_text(message)
                            else:
                                await client_ws.send_bytes(message)
                    except Exception:
                        pass

                upstream_task = asyncio.create_task(upstream_to_client())

                try:
                    while True:
                        msg = await client_ws.receive()
                        if msg.get("type") == "websocket.disconnect":
                            break
                        if msg.get("text") is not None:
                            await upstream.send(msg["text"])
                        elif msg.get("bytes") is not None:
                            await upstream.send(msg["bytes"])
                except WebSocketDisconnect:
                    pass
                finally:
                    upstream_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await upstream_task
        except Exception as exc:
            logger.warning("voice proxy upstream error: %s", exc)
            await _send_error(
                client_ws,
                code="voice_unavailable",
                detail=str(exc)[:200],
            )
            with contextlib.suppress(Exception):
                await client_ws.close(code=1011, reason="upstream")

    @router.post("/voice/telemetry")
    async def voice_telemetry(body: dict) -> dict:
        row = {"ts": time.time(), **body}
        telemetry_log.parent.mkdir(parents=True, exist_ok=True)
        with telemetry_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return {"ok": True}

    return router
