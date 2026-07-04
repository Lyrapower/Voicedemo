from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware

from telemetry.garden_api import router as garden_router

from .grid_route import router as grid_route_router
from .router import router

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from compiler import SemanticMapper
    from models import get_loader
    from models.aster_config import load_aster_config, section
    from models.local_router_store import get_local_router_store
    from models.plugin_loader import get_plugins

    cfg = load_aster_config()
    store = get_local_router_store()
    plugins = get_plugins()

    app.state.loader = get_loader()
    app.state.mapper = SemanticMapper()
    app.state.anchor_loader = None
    app.state.memory = None
    app.state.router_store = store
    app.state.plugins = plugins
    app.state.aster_config = cfg

    identity = section("identity")
    logger.info(
        "Aster %s:%s ready — identity=%s db=%s plugins=%s",
        section("channel").get("host", "127.0.0.1"),
        section("channel").get("port", 8787),
        identity.get("name", "aster"),
        store.db_path,
        list(plugins.keys()),
    )
    yield


app = FastAPI(title="Aster", version="1.0", lifespan=lifespan)

DEV_PROXY = "http://127.0.0.1:5173"


def _aster_channel() -> tuple[str, int]:
    from models.aster_config import channel_host, channel_port

    return channel_host(), channel_port()


def _cors_origins() -> list[str]:
    host, port = _aster_channel()
    return [
        f"http://{host}:{port}",
        f"http://localhost:{port}",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def _vite_down() -> HTMLResponse:
    host, port = _aster_channel()
    return HTMLResponse(
        status_code=503,
        content=(
            "<h1>Sound-Lab dev-server not running</h1>"
            "<p>Start runtime on <strong>127.0.0.1:5173</strong>:</p>"
            "<pre><code>python3 -m uvicorn scripts.sound_lab_fallback:app --host 127.0.0.1 --port 5173</code></pre>"
            f"<p>Then reload <code>http://{host}:{port}/</code>.</p>"
        ),
    )


_proxy_client: httpx.AsyncClient | None = None


def _get_proxy_client() -> httpx.AsyncClient:
    """Shared client: per-request AsyncClient construction costs a full
    connection-pool setup + TCP handshake; reuse keeps keep-alive sockets warm."""
    global _proxy_client
    if _proxy_client is None or _proxy_client.is_closed:
        _proxy_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=2.0))
    return _proxy_client


class ViteDevProxyMiddleware(BaseHTTPMiddleware):
    """GET/HEAD → 5173 except API, health, stream, docs."""

    async def dispatch(self, request: Request, call_next):
        if request.scope["type"] != "http":
            return await call_next(request)
        if request.method not in ("GET", "HEAD"):
            return await call_next(request)
        path = request.url.path
        if (
            path == "/health"
            or path.startswith("/api/")
            or path.startswith("/docs")
            or path.startswith("/openapi")
            or path.startswith("/redoc")
            or path.startswith("/stream")
            or path.startswith("/route")
            or path.startswith("/substrates")
            or path.startswith("/carriers")
            or path.startswith("/audit")
        ):
            return await call_next(request)

        target = f"{DEV_PROXY}{path}"
        if request.url.query:
            target += f"?{request.url.query}"
        try:
            cli = _get_proxy_client()
            if request.method == "HEAD":
                r = await cli.head(target, follow_redirects=True)
                return Response(status_code=r.status_code, headers=dict(r.headers))
            r = await cli.get(target, follow_redirects=True)
        except httpx.RequestError:
            return _vite_down()

        ct = r.headers.get("content-type", "text/html; charset=utf-8")
        out = Response(content=r.content, status_code=r.status_code, media_type=ct)
        out.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return out


@app.get("/health")
async def health():
    from telemetry.live_tts import tts_status
    from telemetry.substrate_health import build_substrate_health

    substrates_available = 0
    substrates_total = 0
    loader = getattr(app.state, "loader", None)
    if loader is not None:
        subs = loader.list_substrates()
        substrates_total = len(subs)
        substrates_available = sum(
            1 for s in subs.values() if s and s.get("available")
        )
    status = "ok" if substrates_available > 0 else "degraded"
    aster_cfg = getattr(app.state, "aster_config", {}) or {}
    identity = aster_cfg.get("identity", {}) or {}
    router_store = getattr(app.state, "router_store", None)
    host, port = _aster_channel()
    substrate = build_substrate_health(
        compiler_ready=substrates_available > 0,
        substrates_available=substrates_available,
        substrates_total=substrates_total,
        compiler_role=identity.get("role"),
    )
    return {
        "status": status,
        "identity": identity,
        "substrates_available": substrates_available,
        "substrates_total": substrates_total,
        "channel": {"host": host, "port": port},
        "primary_backend": getattr(
            getattr(app.state, "loader", None), "backend", "lmstudio"
        ),
        "config": "config/aster.toml",
        "database": str(getattr(router_store, "db_path", "local_router.db")),
        "plugins_loaded": list(getattr(app.state, "plugins", {}).keys()),
        "routes": ["/health", "/stream", "/route", "/map_intent", "/api/memory/*", "/audit"],
        "garden": tts_status(),
        "substrate": substrate,
    }


app.include_router(garden_router)
app.include_router(grid_route_router)
app.include_router(router)
app.add_middleware(ViteDevProxyMiddleware)
