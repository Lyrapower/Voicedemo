"""8501 cloud model routing — GLM / Kimi K2.6 / DeepSeek via Ollama :11434 proxy."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from code_task.cloud_attachments import preprocess_cloud_attachments
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

# 2026-08-05 seal: cloud-* store archived; chat OK; no soul/recall inject; no store memory.
# Unlock store+inject: CLOUD_MEMORY_SEALED=0. /task/expanded 不受此开关影响.
def _cloud_memory_sealed() -> bool:
    return (os.environ.get("CLOUD_MEMORY_SEALED", "1").strip() or "1") != "0"

# ctx 实数(Ollama Cloud library):glm-5.2:cloud=976000 · glm-5.3-flash:cloud=1000000
GLM52_CONTEXT_TOKENS = 976_000
KIMI_CONTEXT_TOKENS = 256_000
GLM53_CONTEXT_TOKENS = 1_000_000
GLM53_FULL_CONTEXT_TOKENS = 1_000_000
_SUBSTRATE_SURFACE = {
    "glm52": "cloud-glm",
    "deepseek_v4": "cloud-deepseek",
    "glm53": "cloud-glm53",
    "glm53_full": "cloud-glm53-full",
}

_SUBSTRATE_CONFIG_KEYS: dict[str, tuple[str, str]] = {
    "glm52": ("glm52_cloud_model", "glm52_cloud_endpoint"),
    "deepseek_v4": ("deepseek_v4_cloud_model", "deepseek_v4_cloud_endpoint"),
    "glm53": ("glm53_flash_cloud_model", "glm53_flash_cloud_endpoint"),
    "glm53_full": ("glm53_full_cloud_model", "glm53_full_cloud_endpoint"),
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
        "glm-5.3-flash": config.get("glm53_flash_cloud_model"),
        "glm-5.3": config.get("glm53_full_cloud_model"),
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
        substrate=substrate,
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
    """注入魂组到最后一条 user(GLM/Kimi build_messages 会丢弃 client system)。

    多轮(≥2 条 user/assistant)=只加召回,不叠近程窗(近程已由客户端 15∩10k 多轮承担)。
    单条 user=近程窗+召回。块级不再套 4000 字上限。
    """
    if _cloud_memory_sealed():
        return list(messages or [])
    # b11 已客户端组装 15窗+top4 时禁止服务端再叠魂组全量
    if os.environ.get("CLOUD_CLIENT_BUILT_MEMORY", "").strip() == "1":
        return list(messages or [])
    if inject_messages is None:
        return list(messages or [])
    path = (db or os.environ.get("GRID_STORE_DB") or DEFAULT_STORE_DB or "").strip()
    if not path or not os.path.isfile(path):
        return list(messages or [])
    out = [dict(m) for m in (messages or [])]
    dial = [m for m in out if m.get("role") in ("user", "assistant")]
    # 客户端多轮→只召回;单条 user→近程窗+召回
    use_window = bool(window) if window is not None else len(dial) < 2
    try:
        prefix = inject_messages(
            path, surface, _last_user_text(out),
            window=use_window, max_chars=None,
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


# P1: store 原文只读工具 —— 给 GLM(侯)查 cloud-* 对话原文(日记层不开放)。
try:
    from code_task.cloud_store_tools import execute_tool as _store_execute_tool, TOOL_DECLARATION as _STORE_TOOL_DECLARATION  # noqa: E402
except Exception:  # pragma: no cover
    _store_execute_tool = None  # type: ignore
    _STORE_TOOL_DECLARATION = None


def _make_store_tool_executor(substrate: str):
    """构造 tool_executor(name, args) -> str。只读 sqlite,不写 store。无工具依赖时返回 None。"""
    if _store_execute_tool is None:
        return None
    # cloud_nodes 按底座选(侯=glm52 → cloud-glm52 + cloud + cloud-kimi)
    if substrate == "glm53":
        nodes = ["cloud-glm53", "cloud", "cloud-glm52"]
    elif substrate == "glm53_full":
        nodes = ["cloud-glm53-full", "cloud", "cloud-glm52"]
    elif substrate == "deepseek_v4":
        nodes = ["cloud-deepseek", "cloud", "cloud-glm52"]
    else:
        nodes = ["cloud-glm52", "cloud", "cloud-kimi"]

    def _exec_wrapper(name: str, args: dict[str, str]) -> str:
        return _store_execute_tool(name, args, cloud_nodes=nodes)

    return _exec_wrapper


async def task_cloud_chat_handler(body: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    import json
    import logging

    log = logging.getLogger("grid.cloud_chat")
    # sealed:仍允许推理 chat; _with_soul_inject 在 sealed 时为空操作(无回忆注入)
    substrate = resolve_substrate(body.get("substrate"))
    spec = CLOUD_SUBSTRATES[substrate]
    model, endpoint = _cfg_model_endpoint(config, substrate)
    rid = str(body.get("request_id") or uuid4())
    # Attachments: text/pdf → inject; GLM images → M3 eyes; DeepSeek → Kimi VL
    body_pp, attach_meta = await preprocess_cloud_attachments(
        body, substrate, config=config, route_id=rid
    )
    messages = body_pp.get("messages") or []
    if not messages:
        raise ValueError("messages required")
    # GLM 5.2/5.3 never receive pixels; M3 already transcribed.
    images = None
    surface = str(body_pp.get("surface") or body.get("surface") or _SUBSTRATE_SURFACE.get(substrate) or "cloud-glm")
    # 注入前体积(客户端原样)
    try:
        pre_bytes = len(json.dumps({"messages": messages}, ensure_ascii=False).encode("utf-8"))
    except Exception:
        pre_bytes = -1
    # b11 Cloud 已 buildCloudStoreMessages → 禁止再魂组全量叠注
    if body.get("client_built_memory") or body.get("memory_sealed"):
        pass
    else:
        messages = _with_soul_inject(messages, surface=surface)
    try:
        post_bytes = len(json.dumps({"messages": messages}, ensure_ascii=False).encode("utf-8"))
    except Exception:
        post_bytes = -1
    log.info(
        "cloud_chat outbound payload_bytes pre=%s post=%s surface=%s substrate=%s "
        "ctx_limit=%s attach=%s",
        pre_bytes, post_bytes, surface, substrate,
        GLM52_CONTEXT_TOKENS if substrate == "glm52"
        else (GLM53_CONTEXT_TOKENS if substrate == "glm53"
        else (GLM53_FULL_CONTEXT_TOKENS if substrate == "glm53_full" else KIMI_CONTEXT_TOKENS)),
        bool(attach_meta.get("preprocess")),
    )
    resp = await execute_cloud_chat(
        request_id=rid,
        messages=messages,
        endpoint=endpoint,
        model=str(body_pp.get("model") or body.get("model") or model).strip(),
        build_messages=spec["build_messages"],
        source=f"task_cloud_chat:{substrate}",
        images=images,
        max_tokens=int(body.get("max_tokens") or config.get("task_max_tokens") or 4096),
        temperature=float(body.get("temperature") or 0.3),
        timeout=float(body.get("timeout") or 300.0),
        substrate=substrate,
        tool_executor=_make_store_tool_executor(substrate),
        tool_declaration=_STORE_TOOL_DECLARATION,
    )
    out = resp.to_dict()
    out["substrate"] = substrate
    out["payload_bytes"] = {"pre": pre_bytes, "post": post_bytes}
    if attach_meta.get("preprocess"):
        out["attachment_meta"] = attach_meta
    if body.get("mission_ref") is not None:
        out["mission_ref"] = body.get("mission_ref")
    eyes = attach_meta.get("eyes") if isinstance(attach_meta, dict) else None
    if isinstance(eyes, dict) and (eyes.get("records") or eyes.get("refs")):
        from code_task.m3_vl_eyes import (
            format_glm_audit_record,
            persist_allowed,
            persist_eyes_messages,
        )

        ok_persist, node_id = persist_allowed(body)
        surface = str(
            body_pp.get("surface")
            or body.get("surface")
            or _SUBSTRATE_SURFACE.get(substrate)
            or "cloud-glm"
        )
        store_msgs: list[dict[str, Any]] = []
        for rec in eyes.get("records") or []:
            store_msgs.append({
                "role": "system",
                "content": rec,
                "surface": surface,
                "substrate": "minimax_m3",
            })
        if resp.ok:
            store_msgs.append({
                "role": "system",
                "content": format_glm_audit_record(
                    list(eyes.get("refs") or []),
                    str(out.get("content") or ""),
                    substrate=substrate,
                    route_id=rid,
                    glm_model=str(out.get("model") or ""),
                ),
                "surface": surface,
                "substrate": substrate,
            })
        wrote = 0
        if ok_persist and store_msgs:
            try:
                wrote = persist_eyes_messages(store_msgs, node_id=node_id)
            except Exception as exc:
                log.warning("eyes provenance persist failed node=%s err=%s", node_id, exc)
                wrote = 0
        eyes["store_node"] = node_id if ok_persist else ""
        eyes["store_wrote"] = int(wrote or 0)
        out["eyes"] = {
            "vl_backend": "minimax_m3",
            "vl_ok": eyes.get("vl_ok"),
            "refs": eyes.get("refs") or [],
            "store_node": eyes.get("store_node"),
            "store_wrote": eyes.get("store_wrote"),
        }
        attach_meta["eyes"] = eyes
        out["attachment_meta"] = attach_meta
        if wrote:
            out["memory_write"] = True
    return out
