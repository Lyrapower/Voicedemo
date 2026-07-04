from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict

import aiohttp


class LlamaCppError(RuntimeError):
    pass


async def stream_llama_cpp_completion(
    session: aiohttp.ClientSession,
    base_url: str,
    prompt: str,
    params: Dict[str, Any],
) -> AsyncIterator[str]:
    payload = {"prompt": prompt, "stream": True}
    payload.update(params)

    async with session.post(f"{base_url.rstrip('/')}/completion", json=payload) as resp:
        if resp.status >= 400:
            raise LlamaCppError(await resp.text())
        async for line in resp.content:
            if not line:
                continue
            raw = line.decode("utf-8", errors="ignore").strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            chunk = data.get("content") or data.get("text") or ""
            if chunk:
                yield chunk
