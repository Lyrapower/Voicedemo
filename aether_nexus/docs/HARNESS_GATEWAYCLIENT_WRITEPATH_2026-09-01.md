# Harness GatewayClient Write-Path 判词 · 2026-09-01 20:05 PDT

> 砥修正档 1:local_gateway.py 一字不出。守恒只看 `grid-resident-harness/harness/gateway.py` 全文(GatewayClient,2KB,非冻结)。
> 三条实况证据锁死 harness→8501 走 `/task/cloud_chat`:戌 8-21 裸 POST 200 · 9-01 glm53 实弹 200 · `/v1/chat/completions` 对 demo/aster 8-17 403。
> 段一 write path 只判:GatewayClient 现打端点是否 `/task/cloud_chat`,不是的话改成什么。

---

## 一、`grid-resident-harness/harness/gateway.py` 全文(51 行,非冻结,无硬编码密钥)

```python
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
```

---

## 二、段一 write path 判词

**GatewayClient 现在打的不是 `/task/cloud_chat`。**

| 方法 | 现打端点 | payload | 响应解析 |
|---|---|---|---|
| `chat()` | `POST /v1/chat/completions` | `{"model":route,"messages":...,"stream":False}` | `resp["choices"][0]["message"]["content"]` |
| `chat_stream()` | `POST /v1/chat/completions` | `{"model":route,"messages":...,"stream":True}` | SSE `delta.content` |

三条实况证据锁死 harness→8501 应走 **`/task/cloud_chat`**(8-21 裸 POST 200 · 9-01 glm53 实弹 200 · `/v1/chat/completions` 对 demo/aster 8-17 **403**)。GatewayClient 现打 `/v1/chat/completions` = **错端点**,对 cloud substrate 会吃 403(链路校验)或拿不到 cloud 多轮/工具能力。

---

## 三、要改成什么(连带三处,不只换路径)

1. **端点**:`/v1/chat/completions` → `/task/cloud_chat`(`chat` + `chat_stream` 都改)
2. **payload schema**:`{"model":route,...}` → `{"substrate":route,"messages":...,"max_tokens":...,"memory_sealed":...}` —— 无 `model` 字段(用 `substrate`),无 `stream`(`/task/cloud_chat` 非流式)
3. **响应解析** `extract_text`:`resp["choices"][0]["message"]["content"]` → `resp["content"]`(`/task/cloud_chat` 返 `{ok,content,usage,done_reason}`)
4. **chat_stream**:`/task/cloud_chat` 不支持流式 → 要么删掉、要么保留但 harness 不调(否则 `aiter_lines` 拿不到 SSE 会挂)

**一句话**:GatewayClient.chat() 现打 `/v1/chat/completions`(错),要改成 `/task/cloud_chat` + 换 substrate payload + 换 `extract_text` 解析 + 去流式。

---

## 四、其他四份(不变,按守恒列留档)

- `memory_adapter.py` 写入接口签名(def 行 + docstring)
- `api.py` `/api/capabilities` 响应 schema
- `HARNESS_CLOSEOUT_DI_v1_3` 全文(判词文档)
- 8-03 裁决原文(历史决定)

这四份"不变",未重出。需补采哪一份原文,说一声。

---

## 五、状态

- **未动代码**:只判,未改 `gateway.py`(非冻结但属 harness 写路径,等拍"改"再动)
- **未碰红线**:local_gateway.py 一字未出;harness gateway.py 只读 + 判词


—— 戌,2026-09-01 PDT
