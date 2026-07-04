from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List

import aiohttp


class OllamaError(RuntimeError):
    pass


async def stream_ollama_chat(
    session: aiohttp.ClientSession,
    base_url: str,
    model: str,
    messages: List[Dict[str, Any]],
    options: Dict[str, Any],
) -> AsyncIterator[str]:
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": options,
    }
    async with session.post(f"{base_url.rstrip('/')}/api/chat", json=payload) as resp:
        if resp.status >= 400:
            raise OllamaError(await resp.text())
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
            msg = data.get("message") or {}
            chunk = msg.get("content") or ""
            if chunk:
                yield chunk
