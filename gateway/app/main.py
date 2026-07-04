"""Private AI Gateway: 127.0.0.1 only, token+scope, audit, kill-switch, minimal API."""
import time
from typing import Optional

from fastapi import FastAPI, Header, Request, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import HOST

def _is_kill() -> bool:
    import os
    return os.environ.get("GATEWAY_KILL", "0").strip().lower() in ("1", "true", "yes")
from app.auth import verify_token, require_scope, TokenInfo
from app.rate_limit import check_and_consume
from app.audit import log as audit_log
from app.models import (
    ChatRequest,
    ChatResponse,
    TTSRequest,
    TTSResponse,
    VisionRequest,
    VisionResponse,
)
from app.providers.provider_registry import (
    select_chat_provider,
    select_vision_provider,
    select_tts_provider,
    get_chat_provider,
    get_vision_provider,
    get_tts_provider,
)
from app.providers.claude import ProviderError

# --- Kill-switch message (fixed)
KILL_MSG = "Gateway temporarily disabled by operator (GATEWAY_KILL=1)."

app = FastAPI(
    title="Private AI Gateway",
    docs_url="/docs",
    redoc_url=None,
    openapi_url="/openapi.json" if HOST == "127.0.0.1" else None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_credentials=False,
    allow_methods=[],
    allow_headers=[],
)


def get_bearer(request: Request) -> str:
    auth = request.headers.get("Authorization") or ""
    if not auth.startswith("Bearer "):
        _audit(None, request.url.path, None, 401, error="Missing or invalid Authorization")
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization")
    return auth[7:].strip()


def get_token_info(request: Request, token: str = Depends(get_bearer)) -> TokenInfo:
    info = verify_token(token)
    if not info:
        _audit(None, request.url.path, None, 401, error="Invalid token")
        raise HTTPException(status_code=401, detail="Invalid token")
    return info


def require_scope_dep(scope: str):
    def _dep(request: Request, token_info: TokenInfo = Depends(get_token_info)):
        if not require_scope(token_info, scope):
            _audit(token_info.token_id, request.url.path, scope, 403, error="Insufficient scope")
            raise HTTPException(status_code=403, detail="Insufficient scope")
        return token_info
    return _dep


@app.get("/admin/health")
def admin_health():
    """No auth for health check; but can be restricted to admin scope if desired."""
    return {"status": "ok", "kill": _is_kill()}


@app.get("/admin/tokens", dependencies=[Depends(require_scope_dep("admin"))])
def admin_tokens(token_info: TokenInfo = Depends(get_token_info)):
    import sqlite3
    from app.config import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT token_id, scopes, enabled, daily_used, daily_limit FROM tokens"
    ).fetchall()
    conn.close()
    return {
        "tokens": [
            {
                "token_id": r["token_id"],
                "scopes": r["scopes"],
                "enabled": bool(r["enabled"]),
                "daily_used": r["daily_used"],
                "daily_limit": r["daily_limit"],
            }
            for r in rows
        ]
    }


def _audit(
    token_id: Optional[str],
    endpoint: str,
    scope: Optional[str],
    status: int,
    latency_ms: Optional[int] = None,
    req_bytes: Optional[int] = None,
    resp_bytes: Optional[int] = None,
    error: Optional[str] = None,
    selected_provider: Optional[str] = None,
    provider_fallback: Optional[bool] = None,
    fallback_chain: Optional[str] = None,
    mode: Optional[str] = None,
    task_type: Optional[str] = None,
):
    audit_log(
        token_id=token_id,
        endpoint=endpoint,
        scope=scope,
        status=status,
        latency_ms=latency_ms,
        req_bytes=req_bytes,
        resp_bytes=resp_bytes,
        error=error,
        selected_provider=selected_provider,
        provider_fallback=provider_fallback,
        fallback_chain=fallback_chain,
        mode=mode,
        task_type=task_type,
    )


@app.post("/chat")
def chat(
    request: Request,
    body: ChatRequest,
    token_info: TokenInfo = Depends(require_scope_dep("chat")),
    x_provider: Optional[str] = Header(None, alias="X-Provider"),
):
    t0 = time.perf_counter()
    req_bytes = len(body.model_dump_json().encode())

    if _is_kill():
        _audit(None, "/chat", "chat", 503, int((time.perf_counter() - t0) * 1000), req_bytes, None, KILL_MSG)
        raise HTTPException(status_code=503, detail=KILL_MSG)

    allowed, new_used = check_and_consume(
        token_info.token_id, token_info.daily_limit, token_info.daily_used
    )
    if not allowed:
        _audit(token_info.token_id, "/chat", "chat", 429, None, req_bytes, None, "daily limit exceeded")
        raise HTTPException(status_code=429, detail="Daily request limit exceeded")

    selected, chain = select_chat_provider(
        body.provider, x_provider, body.mode, body.task_type
    )
    mode_str = body.mode.value if body.mode else None
    task_str = body.task_type.value if body.task_type else None
    used_fallback = False
    reply = ""
    for name in chain:
        try:
            prov = get_chat_provider(name)
            reply = prov.chat(body.prompt, body.context)
            selected = name
            break
        except ProviderError:
            used_fallback = True
            continue
        except Exception:
            used_fallback = True
            continue
    if not reply:
        prov = get_chat_provider("mock")
        reply = prov.chat(body.prompt, body.context)
        used_fallback = True
        selected = "mock"

    latency_ms = int((time.perf_counter() - t0) * 1000)
    resp = ChatResponse(
        reply=reply,
        provider=selected,
        selected_provider=selected,
        provider_fallback=used_fallback,
    )
    import json
    resp_bytes = len(json.dumps(resp.model_dump()).encode())
    _audit(
        token_info.token_id,
        "/chat",
        "chat",
        200,
        latency_ms,
        req_bytes,
        resp_bytes,
        None,
        selected,
        used_fallback,
        ",".join(chain),
        mode_str,
        task_str,
    )
    return resp


@app.post("/tts")
def tts(
    request: Request,
    body: TTSRequest,
    token_info: TokenInfo = Depends(require_scope_dep("tts")),
    x_provider: Optional[str] = Header(None, alias="X-Provider"),
):
    t0 = time.perf_counter()
    req_bytes = len(body.model_dump_json().encode())

    if _is_kill():
        _audit(None, "/tts", "tts", 503, int((time.perf_counter() - t0) * 1000), req_bytes, None, KILL_MSG)
        raise HTTPException(status_code=503, detail=KILL_MSG)

    allowed, _ = check_and_consume(
        token_info.token_id, token_info.daily_limit, token_info.daily_used
    )
    if not allowed:
        _audit(token_info.token_id, "/tts", "tts", 429, None, req_bytes, None, "daily limit exceeded")
        raise HTTPException(status_code=429, detail="Daily request limit exceeded")

    selected, chain = select_tts_provider(body.provider, x_provider)
    used_fallback = False
    try:
        prov = get_tts_provider(selected)
        prov.tts(body.text, body.lang, body.voice)
    except Exception:
        used_fallback = True
        prov = get_tts_provider("mock")
        prov.tts(body.text, body.lang, body.voice)
        selected = "mock"

    latency_ms = int((time.perf_counter() - t0) * 1000)
    resp = TTSResponse(
        status="ok",
        note="mock or not configured",
        selected_provider=selected,
        provider_fallback=used_fallback,
    )
    import json
    resp_bytes = len(json.dumps(resp.model_dump()).encode())
    _audit(
        token_info.token_id,
        "/tts",
        "tts",
        200,
        latency_ms,
        req_bytes,
        resp_bytes,
        None,
        selected,
        used_fallback,
        ",".join(chain),
        None,
        None,
    )
    return resp


@app.post("/vision")
def vision(
    request: Request,
    body: VisionRequest,
    token_info: TokenInfo = Depends(require_scope_dep("vision")),
    x_provider: Optional[str] = Header(None, alias="X-Provider"),
):
    t0 = time.perf_counter()
    req_bytes = len(body.model_dump_json().encode())

    if _is_kill():
        _audit(None, "/vision", "vision", 503, int((time.perf_counter() - t0) * 1000), req_bytes, None, KILL_MSG)
        raise HTTPException(status_code=503, detail=KILL_MSG)

    allowed, _ = check_and_consume(
        token_info.token_id, token_info.daily_limit, token_info.daily_used
    )
    if not allowed:
        _audit(token_info.token_id, "/vision", "vision", 429, None, req_bytes, None, "daily limit exceeded")
        raise HTTPException(status_code=429, detail="Daily request limit exceeded")

    selected, chain = select_vision_provider(body.provider, x_provider)
    used_fallback = False
    result = None
    for name in chain:
        try:
            prov = get_vision_provider(name)
            result = prov.vision(body.image_base64, body.task)
            selected = name
            break
        except ProviderError:
            used_fallback = True
            continue
        except Exception:
            used_fallback = True
            continue
    if result is None:
        prov = get_vision_provider("mock")
        result = prov.vision(body.image_base64, body.task)
        used_fallback = True
        selected = "mock"

    latency_ms = int((time.perf_counter() - t0) * 1000)
    resp = VisionResponse(
        summary=result["summary"],
        parsed=result.get("parsed", {}),
        risk_flags=result.get("risk_flags", []),
        next_steps=result.get("next_steps", []),
        selected_provider=selected,
        provider_fallback=used_fallback,
    )
    import json
    resp_bytes = len(json.dumps(resp.model_dump()).encode())
    _audit(
        token_info.token_id,
        "/vision",
        "vision",
        200,
        latency_ms,
        req_bytes,
        resp_bytes,
        None,
        selected,
        used_fallback,
        ",".join(chain),
        None,
        None,
    )
    return resp




# Global exception handler to audit 401/403/429 (handled by HTTPException)
