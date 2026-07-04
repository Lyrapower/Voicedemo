"""LM Studio streaming — local only, no cloud."""

from __future__ import annotations

import json
import urllib.request
from typing import Any, AsyncIterator, Iterator


def stream_lmstudio_chat(
    messages: list[dict[str, Any]],
    *,
    base_url: str,
    model: str,
    timeout_s: float = 300.0,
) -> Iterator[str]:
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "stream": True,
    }
    from lm_studio_auth import lm_auth_headers

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=lm_auth_headers(),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
            content = delta.get("content") or ""
            if content:
                yield content


async def async_stream_lmstudio(
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> AsyncIterator[str]:
    import asyncio

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def _worker() -> None:
        try:
            for piece in stream_lmstudio_chat(messages, **kwargs):
                queue.put_nowait(piece)
        except Exception:
            pass
        finally:
            queue.put_nowait(None)

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _worker)
    while True:
        item = await queue.get()
        if item is None:
            break
        yield item
