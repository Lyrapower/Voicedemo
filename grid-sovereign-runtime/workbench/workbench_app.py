"""
GRID Workbench UI sidecar — static HTML + gateway_verify_proxy (:8515).

APIs live on :8501 gateway (/task/cloud_chat, /task/expanded, /v1/chat/completions).
Cloud 旁路(/cloud/chat · /cloud/memory/* · 8515 sqlite)已于 2026-08-04 下线 → 410.
Do not duplicate gateway routes here. grid.html on :8501 is untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

WORKBENCH_DIR = Path(__file__).resolve().parent
STATIC_DIR = WORKBENCH_DIR / "static"
_REPO_ROOT = WORKBENCH_DIR.parents[1]
_GATEWAY_DIR = WORKBENCH_DIR.parent / "gateway"

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(_GATEWAY_DIR))

from gateway_verify_proxy import proxy_chat_completions, proxy_task_expanded, verification_probe  # noqa: E402

_CLOUD_RETIRED = {
    "ok": False,
    "error": "gone",
    "detail": "8515 Cloud 旁路已下线(P0-3)·推理 POST :8501/task/cloud_chat · 记忆 :8501 store cloud-*",
    "retired": "2026-08-04",
}

app = FastAPI(title="GRID Workbench UI", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8515", "http://localhost:8515"],
    allow_origin_regex=r"https://[^/]+\.ts\.net",
    allow_credentials=True,
    allow_methods=["GET", "HEAD", "OPTIONS", "POST"],
    allow_headers=["*"],
)


def _html_nocache(path: Path, request: Request) -> Response:
    encoded = path.read_bytes()
    body = b"" if request.method == "HEAD" else encoded
    return Response(
        content=body,
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "Content-Length": str(len(encoded)),
        },
    )


@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": "grid-workbench-ui",
        "port": 8515,
        "api_gateway": "8501",
        "gateway_verify": verification_probe(),
        "cloud_bypass": "retired_20260804",
    }


def _cloud_gone() -> JSONResponse:
    return JSONResponse(_CLOUD_RETIRED, status_code=410)


@app.get("/cloud/memory/{lane}")
async def cloud_memory_get(lane: str):
    return _cloud_gone()


@app.post("/cloud/memory/{lane}/turn")
async def cloud_memory_turn(lane: str, body: dict[str, Any]):
    return _cloud_gone()


@app.post("/cloud/memory/{lane}/purge")
async def cloud_memory_purge(lane: str):
    return _cloud_gone()


@app.post("/cloud/memory/{lane}/clear")
async def cloud_memory_clear(lane: str):
    return _cloud_gone()


@app.post("/cloud/chat")
async def cloud_chat(body: dict[str, Any]):
    return _cloud_gone()


@app.post("/glm/chat")
async def glm_chat(body: dict[str, Any]):
    return _cloud_gone()


@app.post("/kimi/chat")
async def kimi_chat(body: dict[str, Any]):
    return _cloud_gone()


FIELD_NOW_URL = "http://127.0.0.1:8795/now.json"


@app.get("/field_now/now.json")
async def field_now_proxy():
    """Read-only proxy → field_now :8795 (b11 场感知; fail-soft)."""
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(
            FIELD_NOW_URL,
            headers={"User-Agent": "workbench-ui/1.0", "Accept": "application/json"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            body = resp.read(4096)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        body = (
            b'{"garden":"idle","anchor_state":"idle","anchor_coherence":null,'
            b'"breath_sync":null,"zone":null}'
        )
    return Response(
        content=body,
        media_type="application/json; charset=utf-8",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.post("/gateway/v1/chat/completions")
async def gateway_chat_proxy(body: dict[str, Any]):
    """b11 STUDIO chat proxy — server-side grid verification → :8501."""
    status, payload = proxy_chat_completions(body)
    return JSONResponse(payload, status_code=status)


@app.post("/gateway/task/expanded")
async def gateway_expanded_proxy(body: dict[str, Any]):
    """b11 EXPANDED — server-side grid verification → :8501 /task/expanded."""
    status, payload = proxy_task_expanded(body)
    return JSONResponse(payload, status_code=status)


@app.get("/")
async def root():
    # Relative Location keeps Tailscale /workbench/ prefix (absolute /… would hit :8501 root).
    return Response(status_code=302, headers={"Location": "grid_workbench_b11.html"})


@app.get("/grid_workbench_b11.html")
@app.head("/grid_workbench_b11.html")
async def b11_html(request: Request):
    path = STATIC_DIR / "grid_workbench_b11.html"
    if not path.is_file():
        raise HTTPException(404, "grid_workbench_b11.html missing")
    return _html_nocache(path, request)


@app.get("/signal_patterns.json")
@app.head("/signal_patterns.json")
async def signal_patterns_json(request: Request):
    """与 b11 `new URL('signal_patterns.json', location.href)` 同源;修订⑤ recall.* 参数唯一源."""
    path = STATIC_DIR / "signal_patterns.json"
    if not path.is_file():
        raise HTTPException(404, "signal_patterns.json missing")
    encoded = path.read_bytes()
    body = b"" if request.method == "HEAD" else encoded
    return Response(
        content=body,
        media_type="application/json; charset=utf-8",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "Content-Length": str(len(encoded)),
        },
    )


@app.get("/grid_multimodal.html")
@app.head("/grid_multimodal.html")
async def multimodal_html(request: Request):
    path = STATIC_DIR / "grid_multimodal.html"
    if not path.is_file():
        raise HTTPException(404, "grid_multimodal.html missing")
    return _html_nocache(path, request)


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn

    host = "127.0.0.1"
    port = 8515
    print(f"GRID Workbench UI → http://{host}:{port} (APIs on :8501)")
    uvicorn.run(app, host=host, port=port, log_level="info")
