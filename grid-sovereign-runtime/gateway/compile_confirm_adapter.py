"""Same-origin Grid C adapter. Server holds 8630 credentials. Not a generic proxy."""
from __future__ import annotations
import hashlib, hmac, json, os, urllib.error, urllib.request
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field


def _store_token() -> str:
    """Env only. Token file must not enable store/compile identity."""
    return (os.environ.get("GRID_STORE_TOKEN") or "").strip()


def _request_secret(request: Request) -> str:
    hdr = (request.headers.get("X-Grid-Token") or "").strip()
    if hdr:
        return hdr
    return (request.cookies.get("grid_store") or "").strip()


def _harness_token() -> str:
    confirm = (os.environ.get("GRID_HARNESS_CONFIRM_TOKEN") or "").strip()
    full = (os.environ.get("GRID_HARNESS_TOKEN") or "").strip()
    return confirm or full


def _harness_url() -> str:
    return (os.environ.get("HARNESS_API") or "http://127.0.0.1:8630").rstrip("/")


def _owner(token: str) -> str:
    return hashlib.sha256(("grid-compile-owner:" + token).encode()).hexdigest()[:24]


def allowed_origins() -> set[str]:
    extra = (os.environ.get("GRID_COMPILE_ORIGINS") or "").strip()
    ts = (os.environ.get("TS_HOST") or "cicimacbook-air.tail76db5b.ts.net").strip()
    out = {
        "http://127.0.0.1:8501",
        "http://localhost:8501",
        "http://127.0.0.1:8515",
        "http://localhost:8515",
        "https://" + ts,
    }
    for part in extra.split(","):
        p = part.strip().rstrip("/")
        if p:
            out.add(p)
    return out


def _origin_ok(request: Request) -> bool:
    origin = (request.headers.get("origin") or "").strip().rstrip("/")
    if not origin or origin == "null":
        return False
    # Ignore client-controlled forward headers; Origin must be in the allowlist.
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    return origin in allowed_origins()


def gate(request: Request) -> str:
    tok = _store_token()
    if not tok:
        return _owner("local-open")
    got = _request_secret(request)
    if not got or not hmac.compare_digest(got, tok):
        raise HTTPException(401, "bad or missing X-Grid-Token")
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if not _origin_ok(request):
            raise HTTPException(403, "origin_rejected")
    elif request.method in {"GET", "HEAD"}:
        origin = (request.headers.get("origin") or "").strip()
        if origin and not _origin_ok(request):
            raise HTTPException(403, "origin_rejected")
    return _owner(tok)


def _8630(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    token = _harness_token()
    if not token:
        return 503, {"detail": "harness_confirm_token_missing"}
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        _harness_url() + path,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token,
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            parsed = json.loads(raw) if raw else {"detail": e.reason}
        except json.JSONDecodeError:
            parsed = {"detail": raw[:200]}
        return e.code, parsed


class RegisterBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str = Field(min_length=1, max_length=8000)
    session_id: str = Field(default="default", max_length=80)


class ConfirmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str = Field(min_length=4, max_length=80)
    binding_hash: str = Field(min_length=8, max_length=128)
    session_id: str = Field(default="default", max_length=80)


def build_router() -> APIRouter:
    r = APIRouter(prefix="/grid/compile", tags=["grid_compile_confirm"])

    @r.post("/register")
    async def register(body: RegisterBody, request: Request):
        owner = gate(request)
        code, doc = _8630("POST", "/compile/register", {
            "goal": body.goal,
            "session_id": body.session_id,
            "owner": owner,
        })
        if code >= 300:
            raise HTTPException(code, doc.get("detail") or doc)
        return doc

    @r.post("/confirm")
    async def confirm(body: ConfirmBody, request: Request):
        owner = gate(request)
        code, doc = _8630("POST", "/compile/confirm", {
            "candidate_id": body.candidate_id,
            "binding_hash": body.binding_hash,
            "session_id": body.session_id,
            "owner": owner,
        })
        if code >= 300:
            raise HTTPException(code, doc.get("detail") or doc)
        return doc

    @r.get("/map/{candidate_id}")
    async def mapping(candidate_id: str, request: Request):
        owner = gate(request)
        code, doc = _8630("GET", f"/compile/map/{candidate_id}?owner={owner}")
        if code >= 300:
            raise HTTPException(code, doc.get("detail") or doc)
        return doc

    return r
