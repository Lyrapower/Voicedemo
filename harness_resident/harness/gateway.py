"""harness/gateway.py · GatewayClient v2.1(2026-09-02,砥)· 段一件 1

v2.1:route 分流——带斜杠 = model id(本地 qwen/qwen3.5-9b)走 /v1/chat/completions;不带 = substrate 走 /task/cloud_chat;demo/aster 任何路都拒;content 为空一律抛错(200 不算通)。

替换 grid-resident-harness/harness/gateway.py(原 51 行打 /v1/chat/completions,对 cloud substrate 吃 403 且无工具)。
改四处:端点 /task/cloud_chat · payload {"substrate": route, ...} · extract_text 读 resp["content"] · 去流式。
默认 memory_sealed=True(harness 调用不写 cloud 魂),memory_read 由调用方按决策类显式关(旗标名待 gateway 侧确认;
未知旗标 gateway 会忽略,不会报错——所以这里传了也不算"已封读",封读以 gateway 回包 memory_turns==0 为准)。

接口对 supervisor 不变:GatewayClient(cfg) · await ready() · await chat(route, messages, **opts) · extract_text(resp) · close()
chat_stream 保留签名但不再流式:一次拿完整 content 后按行 yield,调用方零改动。

  python3 harness_gateway_client_v2_1.py selftest     # 本地 stub 8501,零出网
"""
from __future__ import annotations
from typing import Any, AsyncIterator
import json


def _headers_from_config():
    try:
        from .config import gateway_headers   # type: ignore
        return gateway_headers()
    except Exception:  # 独立自测时无 package
        return {}


class GatewayClient:
    def __init__(self, cfg: Any, *, client: Any = None):
        import httpx
        self.cfg = cfg
        base = str(getattr(cfg.core, "gateway_base", "http://127.0.0.1:8501")).rstrip("/")
        self.client = client or httpx.AsyncClient(base_url=base, timeout=float(getattr(cfg.core, "gateway_timeout_seconds", 300.0)),
                                                  headers=_headers_from_config())
        self.default_max_tokens = int(getattr(cfg.core, "max_tokens", 1024))

    async def close(self):
        await self.client.aclose()

    async def ready(self) -> bool:
        for path in ("/ready", "/health", "/v1/models"):
            try:
                r = await self.client.get(path)
                if r.status_code < 500:
                    return True
            except Exception:
                pass
        return False

    async def chat(self, route: str, messages: list[dict[str, Any]], *, max_tokens: int | None = None,
                   temperature: float = 0.3, timeout: float | None = None, memory_sealed: bool = True,
                   memory_read: bool | None = None, mission_id: str | None = None) -> dict:
        """route = /task/cloud_chat 的 substrate id(glm52 / glm53 / qwen35 …),不是 model 名。"""
        if "/" in route:                       # model id(qwen/qwen3.5-9b …)→ 本地 openai 路;demo/aster 永远拒
            if route == "demo/aster":
                raise GatewayError("demo/aster is not a lane")
            r = await self.client.post("/v1/chat/completions", json={"model": route, "messages": messages,
                                                                     "max_tokens": int(max_tokens or self.default_max_tokens), "temperature": temperature, "stream": False})
            if r.status_code >= 400:
                raise GatewayError(f"/v1/chat/completions {r.status_code}: {r.text[:200]}")
            d = r.json()
            try:
                content = d["choices"][0]["message"]["content"] or ""
            except Exception as e:
                raise GatewayError(f"unexpected openai response: {str(d)[:200]}") from e
            if not content.strip():
                raise GatewayError("empty content from local lane")
            out = {"ok": True, "content": content, "substrate": route, "model": d.get("model", route), "backend": "local",
                    "usage": d.get("usage") or {}, "route_id": d.get("id")}
            _assert_model_match(route, out)
            return out
        payload: dict[str, Any] = {"substrate": route, "messages": messages,
                                   "max_tokens": int(max_tokens or self.default_max_tokens), "temperature": temperature,
                                   "memory_sealed": bool(memory_sealed)}
        if timeout is not None: payload["timeout"] = float(timeout)
        if memory_read is not None: payload["memory_read"] = bool(memory_read)
        if mission_id: payload["mission_id"] = mission_id
        r = await self.client.post("/task/cloud_chat", json=payload)
        if r.status_code >= 400:
            raise GatewayError(f"/task/cloud_chat {r.status_code}: {r.text[:200]}")
        data = r.json()
        if not data.get("ok", True) and not data.get("content"):
            raise GatewayError(f"gateway ok=false: {str(data.get('error') or data.get('done_reason'))[:200]}")
        if not str(data.get("content") or "").strip():
            raise GatewayError(f"empty content (done_reason={data.get('done_reason')}):200 不算通")
        _assert_model_match(route, data)
        return data

    async def chat_stream(self, route: str, messages: list[dict[str, Any]], **opts) -> AsyncIterator[str]:
        """非流式端点:一次拿完,按行 yield。保留签名给旧调用方。"""
        data = await self.chat(route, messages, **opts)
        text = self.extract_text(data)
        for line in text.splitlines(keepends=True):
            yield line

    @staticmethod
    def extract_text(resp: dict) -> str:
        try:
            c = resp["content"]
            return c if isinstance(c, str) else str(c)
        except Exception as e:
            raise GatewayError(f"unexpected gateway response: {str(resp)[:200]}") from e

    @staticmethod
    def usage(resp: dict) -> dict:
        """给 tool_log / 计价:cost_usd、tool_rounds、memory_turns、backend。"""
        u = resp.get("usage") or {}
        return {"cost_usd": u.get("cost_usd"), "tool_rounds": u.get("tool_rounds"), "memory_turns": u.get("memory_turns"),
                "backend": resp.get("backend"), "model": resp.get("model"), "substrate": resp.get("substrate"),
                "memory_write": resp.get("memory_write"), "route_id": resp.get("route_id")}


class GatewayError(RuntimeError):
    pass


class ModelMismatch(GatewayError):
    """响应 model ≠ 请求 route。gateway T2 静默 fallback 的 harness 侧兜底(D3)。"""


def _assert_model_match(requested: str, resp: dict) -> None:
    resolved = resp.get("model") or resp.get("substrate")
    if requested and resolved and str(resolved) != str(requested):
        raise ModelMismatch(f"requested {requested!r} resolved {resolved!r}")


# ---------- 自测:stub 8501 ----------

def selftest() -> int:
    import asyncio, httpx
    seen: list[dict] = []

    def app(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p == "/health": return httpx.Response(200, json={"ok": True})
        if p == "/v1/chat/completions":
            body = json.loads(request.content); seen.append(body)
            if body.get("model") == "demo/aster": return httpx.Response(403, text="signature required")
            return httpx.Response(200, json={"id": "o1", "model": body["model"], "choices": [{"message": {"content": "local pong"}}], "usage": {}})
        if p == "/task/cloud_chat":
            body = json.loads(request.content); seen.append(body)
            if body.get("substrate") == "__bogus__": return httpx.Response(400, json={"error": "unknown substrate"})
            if body.get("substrate") == "demo/aster": return httpx.Response(403, json={"error": "aster not a lane"})
            if body.get("substrate") == "glm53_full": return httpx.Response(200, json={"ok": True, "content": "", "done_reason": "length", "usage": {}})
            return httpx.Response(200, json={"ok": True, "content": "pong\nline2", "substrate": body["substrate"], "model": "glm-5.3-flash",
                                             "memory_write": not body.get("memory_sealed"), "backend": "ollama_cloud", "route_id": "r1",
                                             "usage": {"cost_usd": 0.001, "tool_rounds": 0, "memory_turns": 0 if body.get("memory_read") is False else 2}})
        return httpx.Response(404)

    class Core:  # 最小 cfg
        gateway_base = "http://stub"; gateway_timeout_seconds = 5.0; max_tokens = 64
    class Cfg:
        core = Core()

    fails: list[str] = []
    must = lambda c, m: (None if c else fails.append(m))

    async def go():
        gc = GatewayClient(Cfg(), client=httpx.AsyncClient(base_url="http://stub", transport=httpx.MockTransport(app)))
        must(await gc.ready(), "1 ready 应 True")
        r = await gc.chat("glm53", [{"role": "user", "content": "pong"}])
        must(seen[-1]["substrate"] == "glm53" and "model" not in seen[-1] and "stream" not in seen[-1], "2 payload 应 substrate,无 model/stream")
        must(seen[-1]["memory_sealed"] is True, "3 默认 memory_sealed=True")
        must(GatewayClient.extract_text(r) == "pong\nline2", "4 extract_text 读 content")
        must(GatewayClient.usage(r)["memory_write"] is False, "5 sealed → memory_write False")
        r2 = await gc.chat("glm52", [{"role": "user", "content": "x"}], memory_read=False, mission_id="m-1")
        must(seen[-1]["memory_read"] is False and seen[-1]["mission_id"] == "m-1", "6 memory_read/mission_id 透传")
        must(GatewayClient.usage(r2)["memory_turns"] == 0, "6b 封读 → memory_turns 0(以回包为准)")
        chunks = [c async for c in gc.chat_stream("glm53", [{"role": "user", "content": "pong"}])]
        must("".join(chunks) == "pong\nline2" and len(chunks) == 2, "7 chat_stream 非流式按行 yield")
        try:
            await gc.chat("__bogus__", []); must(False, "8 400 未抛")
        except GatewayError as e:
            must("400" in str(e), "8 错误含状态码")
        try:
            await gc.chat("demo/aster", []); must(False, "9 demo/aster 403 未抛")
        except GatewayError:
            pass
        r3 = await gc.chat("qwen/qwen3.5-9b", [{"role": "user", "content": "pong"}])
        must(seen[-1].get("model") == "qwen/qwen3.5-9b" and r3["backend"] == "local" and GatewayClient.extract_text(r3) == "local pong", "10 本地 model id 走 /v1/chat/completions")
        try:
            await gc.chat("glm53_full", [{"role": "user", "content": "pong"}]); must(False, "11 空 content 未抛")
        except GatewayError as e:
            must("empty content" in str(e), "11 空 content 错误文案")
        await gc.close()

    asyncio.run(go())
    if fails:
        print("SELFTEST FAIL"); [print(" -", f) for f in fails]; return 1
    print("SELFTEST PASS 11/11(cloud 路 /task/cloud_chat · 本地 model id 走 /v1/chat/completions · demo/aster 拒 · sealed 默认 · extract_text · usage · 封读透传 · 非流式 · 400/403 抛错 · 空 content 不算通)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(selftest() if len(sys.argv) > 1 and sys.argv[1] == "selftest" else 2)
