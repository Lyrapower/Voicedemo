"""8501 cloud model routing — GLM / Kimi K2.6 / DeepSeek via Ollama :11434 proxy."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from code_task.cloud_chat_executor import execute_cloud_chat
from code_task.cloud_substrates import CLOUD_SUBSTRATES, resolve_substrate

_DEMO_ROOT = Path(__file__).resolve().parents[1]
if str(_DEMO_ROOT) not in sys.path:
    sys.path.insert(0, str(_DEMO_ROOT))
try:
    from grid_mem import DEFAULT_STORE_DB, inject_messages, soul_of
except Exception:  # pragma: no cover
    DEFAULT_STORE_DB = ""
    inject_messages = None  # type: ignore
    soul_of = None  # type: ignore

# ctx 实数(Ollama Cloud library):glm-5.2:cloud=976000 · kimi-k2.6:cloud=256000
# 注入实用预算=单条 sanitize 上限 8000 的一半=4000 字(拼进最后 user);非 ctx/2(否则无约束)
GLM52_CONTEXT_TOKENS = 976_000
KIMI_CONTEXT_TOKENS = 256_000
INJECT_CHAR_BUDGET = 4_000  # half of MAX_PROMPT_CHARS
_SUBSTRATE_SURFACE = {
    "glm52": "cloud-glm",
    "kimi_k25": "cloud-kimi",
    "deepseek_v4": "cloud-glm",  # DS 无独立魂,暂挂 cloud 魂组读
}

_SUBSTRATE_CONFIG_KEYS: dict[str, tuple[str, str]] = {
    "glm52": ("glm52_cloud_model", "glm52_cloud_endpoint"),
    "kimi_k25": ("kimi_k25_cloud_model", "kimi_k25_cloud_endpoint"),
    "deepseek_v4": ("deepseek_v4_cloud_model", "deepseek_v4_cloud_endpoint"),
}


def _cfg_model_endpoint(config: dict[str, Any], substrate: str) -> tuple[str, str]:
    model_key, endpoint_key = _SUBSTRATE_CONFIG_KEYS[substrate]
    model = str(config.get(model_key) or CLOUD_SUBSTRATES[substrate]["default_model"]).strip()
    endpoint = str(
        config.get(endpoint_key)
        or config.get("ollama_endpoint")
        or "http://localhost:11434/api/chat"
    ).strip()
    return model, endpoint


def cloud_model_catalog(config: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for substrate in _SUBSTRATE_CONFIG_KEYS:
        model, _ = _cfg_model_endpoint(config, substrate)
        if model and model not in out:
            out.append(model)
    return out


def match_cloud_model(request_model: str | None, config: dict[str, Any]) -> tuple[str, str] | None:
    """→ (substrate_key, canonical_model) if request_model is a registered cloud id."""
    raw = (request_model or "").strip()
    if not raw:
        return None
    catalog = {m: m for m in cloud_model_catalog(config)}
    # Ollama sometimes shortens echoed ids; accept alias map to canonical config model.
    aliases = {
        "glm-5.2": config.get("glm52_cloud_model"),
        "kimi-k2.6": config.get("kimi_k25_cloud_model"),
        "kimi-k2.5": "kimi-k2.5:cloud",
        "deepseek-v4-pro": config.get("deepseek_v4_cloud_model"),
        "deepseek-v4-flash": config.get("deepseek_v4_cloud_model"),
        "deepseek-v4": config.get("deepseek_v4_cloud_model"),
    }
    canonical = catalog.get(raw) or aliases.get(raw)
    if not canonical:
        return None
    canonical = str(canonical).strip()
    for substrate in _SUBSTRATE_CONFIG_KEYS:
        model, _ = _cfg_model_endpoint(config, substrate)
        if raw == model or canonical == model:
            return substrate, model
    return None


async def openai_cloud_chat_completion(
    body: dict[str, Any],
    config: dict[str, Any],
    *,
    route_id: str | None = None,
    link_fingerprint_fn,
) -> dict[str, Any]:
    """OpenAI-shaped completion for /v1/chat/completions cloud model requests."""
    request_model = str(body.get("model") or "").strip()
    matched = match_cloud_model(request_model, config)
    if not matched:
        raise ValueError("not a cloud model")
    substrate, canonical_model = matched
    spec = CLOUD_SUBSTRATES[substrate]
    model, endpoint = _cfg_model_endpoint(config, substrate)
    messages = body.get("messages") or []
    if not messages:
        raise ValueError("messages required")
    rid = route_id or str(uuid4())
    resp = await execute_cloud_chat(
        request_id=rid,
        messages=messages,
        endpoint=endpoint,
        model=model,
        build_messages=spec["build_messages"],
        source=f"cloud_chat:{substrate}",
        max_tokens=int(body.get("max_tokens") or config.get("chat_max_tokens") or 1024),
        temperature=float(body.get("temperature") or 0.3),
        timeout=float(body.get("timeout") or 300.0),
    )
    mission_ref = body.get("mission_ref")
    extra_meta = {"cloud_substrate": substrate, "ollama_cloud": True}
    if mission_ref is not None:
        extra_meta["mission_ref"] = mission_ref
    if not resp.ok:
        err = resp.error or {}
        return {
            **link_fingerprint_fn(rid),
            "error": {"type": "cloud_upstream", "message": str(err.get("reason") or resp.done_reason)},
            "model": canonical_model,
            "grid_meta": extra_meta,
        }
    return {
        **link_fingerprint_fn(rid),
        "id": f"chatcmpl-{rid}",
        "object": "chat.completion",
        "created": int(__import__("time").time()),
        "model": canonical_model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": resp.content or ""},
            "finish_reason": resp.done_reason or "stop",
        }],
        "usage": resp.usage or {},
        "grid_meta": extra_meta,
    }


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for m in reversed(messages or []):
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                return c.strip()
            if isinstance(c, list):
                parts = [str(x.get("text") or "") for x in c if isinstance(x, dict)]
                return " ".join(parts).strip()
    return ""


def _with_soul_inject(
    messages: list[dict[str, Any]],
    *,
    surface: str,
    db: str | None = None,
    window: bool | None = None,
) -> list[dict[str, Any]]:
    """注入魂组到最后一条 user(GLM/Kimi build_messages 会丢弃 client system)。"""
    if inject_messages is None:
        return list(messages or [])
    path = (db or os.environ.get("GRID_STORE_DB") or DEFAULT_STORE_DB or "").strip()
    if not path or not os.path.isfile(path):
        return list(messages or [])
    out = [dict(m) for m in (messages or [])]
    dial = [m for m in out if m.get("role") in ("user", "assistant")]
    # 客户端多轮→只召回;单条 user(终批单源组装)→近程窗+召回
    use_window = bool(window) if window is not None else len(dial) < 2
    try:
        prefix = inject_messages(
            path, surface, _last_user_text(out),
            window=use_window, max_chars=INJECT_CHAR_BUDGET,
        )
    except Exception:
        return out
    if not prefix:
        return out
    block = str(prefix[0].get("content") or "").strip()
    if not block:
        return out
    for i in range(len(out) - 1, -1, -1):
        if out[i].get("role") == "user" and isinstance(out[i].get("content"), str):
            cur = out[i]["content"]
            if "[魂组近程]" in cur or "[魂组召回]" in cur:
                return out
            out[i] = {**out[i], "content": block + "\n\n---\n\n" + cur}
            return out
    out.append({"role": "user", "content": block})
    return out

async def task_cloud_chat_handler(body: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    import json
    import logging

    log = logging.getLogger("grid.cloud_chat")
    substrate = resolve_substrate(body.get("substrate"))
    spec = CLOUD_SUBSTRATES[substrate]
    model, endpoint = _cfg_model_endpoint(config, substrate)
    rid = str(body.get("request_id") or uuid4())
    messages = body.get("messages") or []
    if not messages:
        raise ValueError("messages required")
    surface = str(body.get("surface") or _SUBSTRATE_SURFACE.get(substrate) or "cloud-glm")
    # 注入前体积(客户端原样)
    try:
        pre_bytes = len(json.dumps({"messages": messages}, ensure_ascii=False).encode("utf-8"))
    except Exception:
        pre_bytes = -1
    messages = _with_soul_inject(messages, surface=surface)
    try:
        post_bytes = len(json.dumps({"messages": messages}, ensure_ascii=False).encode("utf-8"))
    except Exception:
        post_bytes = -1
    log.info(
        "cloud_chat outbound payload_bytes pre=%s post=%s surface=%s substrate=%s "
        "ctx_limit=%s inject_char_budget=%s",
        pre_bytes, post_bytes, surface, substrate,
        GLM52_CONTEXT_TOKENS if substrate == "glm52" else KIMI_CONTEXT_TOKENS,
        INJECT_CHAR_BUDGET,
    )
    resp = await execute_cloud_chat(
        request_id=rid,
        messages=messages,
        endpoint=endpoint,
        model=str(body.get("model") or model).strip(),
        build_messages=spec["build_messages"],
        source=f"task_cloud_chat:{substrate}",
        max_tokens=int(body.get("max_tokens") or config.get("task_max_tokens") or 4096),
        temperature=float(body.get("temperature") or 0.3),
        timeout=float(body.get("timeout") or 300.0),
    )
    out = resp.to_dict()
    out["substrate"] = substrate
    out["payload_bytes"] = {"pre": pre_bytes, "post": post_bytes}
    if body.get("mission_ref") is not None:
        out["mission_ref"] = body.get("mission_ref")
    return out
