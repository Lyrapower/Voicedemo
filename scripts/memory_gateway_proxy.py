"""DEPRECATED — Entry B (8787) owns MEMORY compile via repo/telemetry/garden_api.py.

Do not point compile at :8500. Override only for legacy experiments:
  COMPILE_GATEWAY_URL=http://127.0.0.1:8787
"""

from __future__ import annotations

import os
from typing import Any

import httpx

COMPILE_GATEWAY_URL = os.environ.get(
    "COMPILE_GATEWAY_URL", "http://127.0.0.1:8787"
).rstrip("/")

_COMPILED_PATH = "/api/memory/compiled"
_COMPILE_PATH = "/api/memory/compile"


async def fetch_compiled_memory() -> dict[str, Any]:
    url = f"{COMPILE_GATEWAY_URL}{_COMPILED_PATH}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=3.0)) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as e:
        return {
            "ok": False,
            "error": f"compile gateway unreachable at {url}: {e}",
            "memory": "",
            "files": [],
            "compiledDir": "",
            "gateway": COMPILE_GATEWAY_URL,
        }


async def post_memory_compile() -> dict[str, Any]:
    url = f"{COMPILE_GATEWAY_URL}{_COMPILE_PATH}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=3.0)) as client:
            resp = await client.post(url)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as e:
        return {
            "ok": False,
            "error": f"compile gateway unreachable at {url}: {e}",
            "gateway": COMPILE_GATEWAY_URL,
        }
