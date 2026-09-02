from __future__ import annotations
from typing import Any, AsyncIterator
import json
import httpx
from .config import Config, gateway_headers

class GatewayClient:
    def __init__(self, cfg: Config):
        self.cfg=cfg
        self.client=httpx.AsyncClient(
            base_url=cfg.core.gateway_base.rstrip("/"),
            timeout=cfg.core.gateway_timeout_seconds,
            headers=gateway_headers()
        )

    async def close(self): await self.client.aclose()

    async def ready(self):
        for path in ("/ready","/health","/v1/models"):
            try:
                r=await self.client.get(path)
                if r.status_code < 500: return True
            except Exception:
                pass
        return False

    async def chat(self, route: str, messages: list[dict[str,Any]]):
        r=await self.client.post("/v1/chat/completions",
                                 json={"model":route,"messages":messages,"stream":False})
        r.raise_for_status()
        return r.json()


    async def chat_stream(self, route: str, messages: list[dict[str,Any]]) -> AsyncIterator[str]:
        payload={"model":route,"messages":messages,"stream":True}
        async with self.client.stream("POST","/v1/chat/completions",json=payload) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data=line[5:].strip()
                if data=="[DONE]":
                    break
                try:
                    obj=json.loads(data)
                    delta=obj["choices"][0].get("delta",{})
                    text=delta.get("content")
                    if text:
                        yield text
                except Exception:
                    continue

    @staticmethod
    def extract_text(resp):
        try:
            return resp["choices"][0]["message"]["content"] or ""
        except Exception as e:
            raise ValueError(f"unexpected gateway response: {resp}") from e
