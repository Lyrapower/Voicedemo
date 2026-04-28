from __future__ import annotations

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .router import router

app = FastAPI(title="Aster Router (Lean)", version="1.0")

# Garden / sound-lab Vite dev-server (start from repo root: bash scripts/start_sound_lab.sh)
DEV_PROXY = "http://127.0.0.1:5173"


def _vite_down() -> HTMLResponse:
    return HTMLResponse(
        status_code=503,
        content=(
            "<h1>Sound-Lab dev-server not running</h1>"
            "<p>Start Vite on <strong>127.0.0.1:5173</strong>:</p>"
            "<pre><code>bash scripts/start_sound_lab.sh</code></pre>"
            "<p>Then reload this page (<code>http://127.0.0.1:8787/</code> proxies to Vite).</p>"
        ),
    )


class ViteDevProxyMiddleware(BaseHTTPMiddleware):
    """GET/HEAD (except API/OpenAPI routes) → Vite :5173 so :8787 serves the particle UI."""

    async def dispatch(self, request: Request, call_next):
        if request.scope["type"] != "http":
            return await call_next(request)
        method = request.method
        if method not in ("GET", "HEAD"):
            return await call_next(request)
        path = request.url.path
        if (
            path == "/health"
            or path.startswith("/docs")
            or path.startswith("/openapi")
            or path.startswith("/redoc")
            or path.startswith("/stream")
        ):
            return await call_next(request)

        q = request.url.query
        target = f"{DEV_PROXY}{path}"
        if q:
            target = f"{target}?{q}"
        timeout = httpx.Timeout(60.0, connect=2.0)
        headers = {"Accept": request.headers.get("accept", "*/*")}
        try:
            async with httpx.AsyncClient(timeout=timeout) as cli:
                if method == "HEAD":
                    r = await cli.head(target, headers=headers, follow_redirects=True)
                    return Response(status_code=r.status_code, headers=dict(r.headers))
                r = await cli.get(target, headers=headers, follow_redirects=True)
        except httpx.RequestError:
            return _vite_down()

        ct = r.headers.get("content-type", "text/html; charset=utf-8")
        out = Response(content=r.content, status_code=r.status_code, media_type=ct)
        for hk in ("cache-control", "etag"):
            if hk in r.headers:
                out.headers[hk] = r.headers[hk]
        return out


@app.get("/health")
async def health():
    return {"status": "ok", "primary_backend": "ollama", "fallback_backend": "llama.cpp"}


app.include_router(router)
app.add_middleware(ViteDevProxyMiddleware)
