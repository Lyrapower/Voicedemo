"""
Pack 4 — optional standalone grid router (not the Aster entry, not Jarvis).
Aster entry: scripts/start_aster.sh → config/aster.toml
Jarvis entry: scripts/start_jarvis.sh → app.platform_main:app :8686
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.logging_config import setup_logging  # noqa: E402
from app.routes import router  # noqa: E402
from compiler import SemanticMapper  # noqa: E402
from models import get_loader  # noqa: E402

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("Grid Router initializing (standalone — no repo merge)...")

    loader = get_loader()
    substrates = loader.list_substrates()

    available_count = sum(
        1 for s in substrates.values() if s and s.get("available")
    )
    allow_degraded = os.environ.get("GRID_ROUTER_ALLOW_DEGRADED", "").lower() in (
        "1",
        "true",
        "yes",
    )

    if available_count == 0 and not allow_degraded:
        logger.error("No substrates available — deploy Packs 1-2 first")
        raise RuntimeError("Substrate layer not ready")

    if available_count == 0:
        logger.warning("Starting degraded — no Ollama substrates (GRID_ROUTER_ALLOW_DEGRADED=1)")

    logger.info("Substrates available: %s/%s", available_count, len(substrates))
    for name, info in substrates.items():
        if not info:
            continue
        status = "ready" if info.get("available") else "unavailable"
        logger.info("  %s: %s (%s)", name, status, info.get("purpose", ""))

    mapper = SemanticMapper()
    logger.info("Semantic mapper initialized")

    app.state.loader = loader
    app.state.mapper = mapper
    app.state.anchor_loader = None
    app.state.memory = None

    logger.info("Grid Router ready (no reference doc loading)")
    yield
    logger.info("Grid Router shutting down")


app = FastAPI(
    title="Grid Router",
    description="Sovereign infrastructure routing layer (Pack 4 — standalone)",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
async def root():
    return {
        "service": "grid_router",
        "version": "0.1.0",
        "status": "operational",
        "note": "Standalone Pack 4 — not merged with repo/app particle router",
    }


@app.get("/health")
async def health():
    loader = app.state.loader
    substrates = loader.list_substrates()
    available = sum(1 for s in substrates.values() if s and s.get("available"))
    return {
        "status": "grid_anchor" if available > 0 else "degraded",
        "substrates_available": available,
        "substrates_total": len(substrates),
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("GRID_ROUTER_PORT", "8792"))
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=port,
        workers=1,
        log_level="info",
    )
