"""Grid compile — reuses repo scripts/garden_services (same as 8787 MEMORY panel)."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.garden_services import compiled_memory_payload, run_memory_compile  # noqa: E402

router = APIRouter(tags=["compile"])


@router.get("/api/memory/compiled")
async def memory_compiled() -> dict:
    return compiled_memory_payload()


@router.post("/api/memory/compile")
async def memory_compile() -> dict:
    return run_memory_compile()
