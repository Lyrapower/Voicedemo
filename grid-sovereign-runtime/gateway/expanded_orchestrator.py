"""POST /task/expanded — server-side orchestration for GRID Workbench b11.

Invariants (2026-08-27 · dual EXPANDED base):
- Cloud substrate **default** = glm52_cloud (glm-5.2:cloud).
- Optional alternate base = glm53_flash_cloud (glm-5.3-flash:cloud) via body.cloud_backend —
  same deploy path (memory / integrate / store); not a silent fallback when GLM-5.2 fails.
  Replaces former Kimi K2.6 second base. Old kimi_* aliases map here.
- EXPANDED-GLM53: native images (model is multimodal).
- EXPANDED-GLM 5.2: K2.6 VL bypass only if expanded_vl_bypass_enabled=true (default off).
"""
from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from code_task.backends import glm52_cloud as glm52_backend
from code_task.backends import glm53_flash_cloud as glm53_backend
from code_task.kimi_input_scope import _reject
from code_task.vl_bypass import describe_images
from expanded_media import preprocess_audio_asset, preprocess_video_asset
from expanded_memory import load_soul_recall, load_store_messages, select_store_memory_snippets
from substrate_backend import resolve_substrate_target
from temperature_policy import CANDIDATE_INTEGRATE_TEMP, resolve_substrate_temperature

RULE_LINE_GLM = (
    "你是 Grid 的扩展 substrate(GLM-5.2 大底座):只完成当前任务;不声称 Grid 权限;"
    "不臆造记忆;数据不足时明说不足。"
)
RULE_LINE_GLM53 = (
    "你是 Grid 的扩展 substrate(GLM-5.3 Flash 大底座):只完成当前任务;不声称 Grid 权限;"
    "不臆造记忆;数据不足时明说不足。"
    "禁止把推理/chain-of-thought写进正文;content只给用户看的回答。"
)
# backward-compat alias (tests / callers)
RULE_LINE = RULE_LINE_GLM
RULE_LINE_KIMI = RULE_LINE_GLM53  # old name: second base is no longer Kimi
EXPANDED_CLOUD_BACKEND = "glm52_cloud"
EXPANDED_CLOUD_BACKENDS = frozenset({"glm52_cloud", "glm53_flash_cloud"})
_BACKEND_ALIASES = {
    "glm52": "glm52_cloud",
    "glm": "glm52_cloud",
    "glm-5.2": "glm52_cloud",
    "glm52_cloud": "glm52_cloud",
    "glm53": "glm53_flash_cloud",
    "glm-5.3-flash": "glm53_flash_cloud",
    "glm53_flash": "glm53_flash_cloud",
    "glm53_flash_cloud": "glm53_flash_cloud",
    # former K2.6 second-base ids → GLM-5.3 Flash
    "kimi": "glm53_flash_cloud",
    "kimi_k25": "glm53_flash_cloud",
    "kimi-k2.6": "glm53_flash_cloud",
    "kimi_k25_cloud": "glm53_flash_cloud",
}


def resolve_expanded_cloud_backend(
    body: dict[str, Any] | None,
    config: dict[str, Any] | None = None,
) -> str:
    """Pick EXPANDED cloud base. Default GLM-5.2; allow explicit GLM-5.3 Flash (same deploy path)."""
    body = body or {}
    config = config or {}
    raw = (
        body.get("cloud_backend")
        or body.get("backend_id")
        or config.get("expanded_cloud_backend")
        or EXPANDED_CLOUD_BACKEND
    )
    key = str(raw or "").strip().lower()
    resolved = _BACKEND_ALIASES.get(key, key)
    if resolved not in EXPANDED_CLOUD_BACKENDS:
        return EXPANDED_CLOUD_BACKEND
    return resolved


def rule_line_for(cloud_backend: str) -> str:
    resolved = _BACKEND_ALIASES.get(str(cloud_backend or "").strip().lower(), cloud_backend)
    return RULE_LINE_GLM53 if resolved == "glm53_flash_cloud" else RULE_LINE_GLM


def substrate_label_for(cloud_backend: str, *, suffix: str = "") -> str:
    resolved = _BACKEND_ALIASES.get(str(cloud_backend or "").strip().lower(), cloud_backend)
    base = "glm53_flash_cloud" if resolved == "glm53_flash_cloud" else "glm52_cloud"
    return f"{base}{suffix}" if suffix else base

TASK_BUDGETS = {"normal": "chat", "visual": "task", "document": "task", "heavy": "task"}

# Short but reasoning-heavy prompts → GLM (same intent as grid_router auto:complexity).
_REASONING_CLOUD_KW = (
    "逐步分析",
    "写完整方案",
    "完整方案",
    "深度分析",
    "详细分析",
    "逐步推理",
    "分步骤",
    "系统性分析",
    "全面评估",
    "对比分析",
    "架构设计",
    "方案设计",
    "权衡",
    "论证",
    "重推理",
    "step by step",
    "step-by-step",
    "trade-off",
    "tradeoff",
    "pros and cons",
)

_OUTBOUND_SAN = re.compile(
    r"/(?:Users|home|var|etc)/[^\s\"'”]+|sk-[A-Za-z0-9]{16,}|"
    r"(?:api[_-]?key|token|secret)\s*[=:]\s*\S+",
    re.I,
)


def task_needs_reasoning_cloud(task: str) -> bool:
    """True when short text still warrants glm-5.2:cloud (heavy reasoning)."""
    low = task.lower()
    return any(kw.lower() in low for kw in _REASONING_CLOUD_KW)


def classify_task_type(task: str, assets: list[dict[str, Any]]) -> str:
    kinds = {str(a.get("kind") or "").lower() for a in assets}
    if kinds & {"video", "audio"}:
        return "heavy"
    if "pdf" in kinds:
        return "document"
    if "image" in kinds:
        return "visual"
    if task_needs_reasoning_cloud(task):
        return "heavy"
    if len(task) > 500:
        return "document"
    text_asset_chars = sum(
        len(str(a.get("text") or ""))
        for a in assets
        if str(a.get("kind") or "").lower() == "text"
    )
    if text_asset_chars > 800:
        return "document"
    return "normal"


def needs_cloud_substrate(task_type: str, assets: list[dict[str, Any]]) -> bool:
    if task_type != "normal":
        return True
    return any(str(a.get("kind") or "").lower() == "image" for a in assets)


def resolve_budget(task_type: str, config: dict[str, Any]) -> int:
    """Dynamic budget from 8501 config — normal uses chat_max_tokens (not 1024)."""
    chat = int(config.get("chat_max_tokens") or 8192)
    task = int(config.get("task_max_tokens") or 4096)
    cap = int(config.get("expanded_max_tokens") or max(chat, task))
    route_key = TASK_BUDGETS.get(task_type, "chat")
    base = chat if route_key == "chat" else task
    return min(base, cap)


def _extract_pdf_text(b64: str, *, limit: int = 12000) -> str:
    try:
        raw = base64.b64decode(b64, validate=False)
    except Exception:
        return ""
    chunks = re.findall(rb"\(([^()\\]{3,})\)", raw)
    parts: list[str] = []
    for chunk in chunks[:800]:
        try:
            parts.append(chunk.decode("utf-8", errors="ignore"))
        except Exception:
            parts.append(chunk.decode("latin-1", errors="ignore"))
    text = " ".join(parts)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def preprocess_assets(
    assets: list[dict[str, Any]],
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    """Return (vl_images, text_blocks, preprocess_meta).

    vl_images are tray frames only used if expanded_vl_bypass_enabled (opt-in Kimi VL).
    Default EXPANDED path does not call Kimi.
    """
    vl_images: list[dict[str, str]] = []
    text_blocks: list[str] = []
    meta: dict[str, Any] = {"assets": len(assets), "kinds": []}

    for asset in assets:
        kind = str(asset.get("kind") or "").lower()
        name = str(asset.get("name") or kind or "asset")
        meta["kinds"].append(kind)

        if kind == "image":
            b64 = str(asset.get("base64") or "").strip()
            mime = str(asset.get("mime") or "image/jpeg").strip()
            if b64:
                vl_images.append({"mime": mime, "base64": b64})
            continue

        if kind == "text":
            text = str(asset.get("text") or "").strip()
            if text:
                text_blocks.append(f"【素材 {name}】\n{text[:20000]}")
            continue

        if kind == "pdf":
            b64 = str(asset.get("base64") or "").strip()
            extracted = _extract_pdf_text(b64) if b64 else ""
            if extracted:
                text_blocks.append(f"【PDF {name} · 本地抽取】\n{extracted[:12000]}")
                meta.setdefault("pdf_extracted", []).append(name)
            else:
                text_blocks.append(f"【PDF {name}】本地未能抽取可读文本。")
            continue

        if kind == "audio":
            b64 = str(asset.get("base64") or "").strip()
            mime = str(asset.get("mime") or "audio/mp4")
            if b64:
                block, ameta = preprocess_audio_asset(b64, name, config)
                text_blocks.append(block)
                meta.setdefault("audio", []).append(ameta)
            else:
                text_blocks.append(f"【音频 {name}】缺少 base64。")
            continue

        if kind == "video":
            b64 = str(asset.get("base64") or "").strip()
            if b64:
                blocks, frames, vmeta = preprocess_video_asset(b64, name, config)
                text_blocks.extend(blocks)
                meta.setdefault("video", []).append(vmeta)
                for frame in frames:
                    if len(vl_images) >= 6:
                        break
                    vl_images.append(frame)
            else:
                text_blocks.append(f"【视频 {name}】缺少 base64。")

    if len(vl_images) > 6:
        vl_images = vl_images[:6]
        meta["images_capped"] = 6
    return vl_images, text_blocks, meta


def sanitize_outbound(text: str) -> tuple[str | None, str | None]:
    reason = _reject(text, field="outbound")
    if reason:
        return None, reason
    if _OUTBOUND_SAN.search(text):
        return None, "outbound matches local path or secret pattern"
    return text, None


def select_memory_snippets(
    *,
    task: str,
    client_context: str,
    max_snippets: int = 3,
) -> tuple[list[str], list[str]]:
    """Compact memory-like snippets from client_context only (whitelist sanitizer)."""
    snippets: list[str] = []
    hits: list[str] = []
    blocks = [b.strip() for b in client_context.split("\n") if b.strip()]
    for block in blocks[-max_snippets * 2 :]:
        clean, reason = sanitize_outbound(block)
        if clean:
            if task[:40] in clean:
                continue
            snippets.append(clean[:400])
        elif reason:
            hits.append(reason)
        if len(snippets) >= max_snippets:
            break
    return snippets, hits


def build_envelope(
    *,
    task: str,
    client_context: str,
    text_blocks: list[str],
    memory_snippets: list[str],
    cloud_backend: str = EXPANDED_CLOUD_BACKEND,
) -> tuple[str, str]:
    parts = [rule_line_for(cloud_backend)]
    if client_context.strip():
        parts.append(f"[近程上下文]\n{client_context.strip()[:2400]}")
    if memory_snippets:
        parts.append("[记忆片段]\n" + "\n".join(f"- {s}" for s in memory_snippets))
    if text_blocks:
        parts.append("\n\n".join(text_blocks))
    parts.append(f"[当前任务]\n{task.strip()}")
    prompt = "\n\n".join(parts)
    summary = (
        f"近6轮紧凑上下文/{len(client_context)//80}段 · "
        f"{len(text_blocks)}素材 · 法则1行 · 记忆片段{len(memory_snippets)}"
    )
    return prompt, summary


def _validate_user_message(
    task: str, candidate: str, *, cloud_backend: str = EXPANDED_CLOUD_BACKEND
) -> str:
    if cloud_backend == "glm53_flash_cloud":
        identity = (
            "substrate 为 Ollama Cloud GLM-5.3 Flash (glm-5.3-flash:cloud)，"
            "不是 GLM-5.2、不是 Kimi、不是 Grid 本体。"
            "以 Grid 法则校验:内容可靠则接纳并按需修正表述;"
            "若 substrate 误报模型身份(如自称 Kimi/GLM-5.2),在最终回答中纠正为 GLM-5.3 Flash,勿复述错误型号;"
        )
    else:
        identity = (
            "substrate 为 Ollama Cloud GLM-5.2 (glm-5.2:cloud)，"
            "不是 GLM-4.5、不是 Kimi、不是 Grid 本体。"
            "以 Grid 法则校验:内容可靠则接纳并按需修正表述;"
            "若 substrate 误报模型身份(如自称 GLM-4.5/Kimi),在最终回答中纠正为 GLM-5.2,勿复述错误型号;"
        )
    return (
        "扩展 substrate 对以下任务的输出已到。"
        + identity
        + "发现越权或臆造则纠正之。直接输出最终回答,不评论流程。\n\n"
        f"[任务]\n{task}\n\n[substrate 输出]\n{candidate}"
    )


def append_telemetry(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


async def run_expanded_orchestration(
    body: dict[str, Any],
    *,
    route_id: str,
    config: dict[str, Any],
    substrate_chat: Callable[..., Awaitable[Any]],
    ensure_aster_messages: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    impersonation_check: Callable[[str], str | None],
    telemetry_path: Path,
    kimi_enabled: bool | None = None,
    store_messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    timing: dict[str, int] = {}
    task = str(body.get("task") or "").strip()
    assets = body.get("assets") if isinstance(body.get("assets"), list) else []
    client_context = str(body.get("client_context") or "")
    cloud_backend = resolve_expanded_cloud_backend(body, config)

    task_type = classify_task_type(task, assets)
    budget = resolve_budget(task_type, config)
    sanitizer_hits: list[str] = []

    t_pre = time.time()
    vl_images, text_blocks, preprocess_meta = preprocess_assets(assets, config)
    vl_warnings: list[str] = []
    native_images: list[dict[str, str]] = []
    vl_bypass_on = bool(config.get("expanded_vl_bypass_enabled"))
    if vl_images and cloud_backend == "glm53_flash_cloud":
        # EXPANDED-GLM53: native multimodal
        native_images = list(vl_images)[:6]
        preprocess_meta["native_images"] = len(native_images)
        vl_images = []
    elif vl_images and vl_bypass_on:
        vl_blocks, vl_warnings, vl_meta = await describe_images(
            vl_images,
            task=task,
            config=config,
            route_id=route_id,
        )
        text_blocks = vl_blocks + text_blocks
        preprocess_meta["vl_bypass"] = vl_meta
        vl_images = []
    elif vl_images:
        n = len(vl_images)
        note = (
            f"【图像×{n}】EXPANDED-GLM 底座=GLM-5.2 纯文本;"
            "Kimi VL bypass 已关闭(expanded_vl_bypass_enabled=false),未识图。"
            "需要读图请切 EXPANDED GLM-5.3 Flash。"
        )
        text_blocks.insert(0, note)
        vl_warnings.append("vl_bypass_disabled_glm52_text_only")
        preprocess_meta["vl_bypass"] = {"skipped": True, "images": n, "reason": "glm_text_only"}
        vl_images = []
    ctx_snippets, ctx_hits = select_memory_snippets(task=task, client_context=client_context)
    store_snippets, store_hits = select_store_memory_snippets(
        store_messages or [], task=task,
    )
    mem_node = str(body.get("memory_node") or "").strip()
    isolated_lane = mem_node.startswith("scout-") or mem_node in {
        "smoke",
        "smoke_node",
        "scout-review",
    }
    # 隔离 lane 不并魂组;b11 魂组须过出网闸(FIELD_NOW 等禁进 cloud)
    soul_recall: list[str] = []
    if not isolated_lane:
        for raw in load_soul_recall(task, surface="b11-expanded", budget=2000):
            clean, reason = sanitize_outbound(raw)
            if clean:
                soul_recall.append(clean)
            elif reason:
                sanitizer_hits.append(f"soul:{reason}")
    memory_snippets = []
    seen_mem: set[str] = set()
    for snippet in store_snippets + soul_recall + ctx_snippets:
        if snippet in seen_mem:
            continue
        seen_mem.add(snippet)
        memory_snippets.append(snippet)
        if len(memory_snippets) >= 6:
            break
    sanitizer_hits.extend(ctx_hits)
    sanitizer_hits.extend(store_hits)
    prompt, envelope_summary = build_envelope(
        task=task,
        client_context=client_context,
        text_blocks=text_blocks,
        memory_snippets=memory_snippets,
        cloud_backend=cloud_backend,
    )
    timing["preprocess"] = int((time.time() - t_pre) * 1000)

    # Legacy body.kimi_enabled / cloud_enabled:
    #   False → force local (factory low budget); None/True → allow selected cloud.
    cloud_flag = body.get("cloud_enabled")
    if cloud_flag is None:
        cloud_flag = kimi_enabled
    use_cloud = needs_cloud_substrate(task_type, assets) and (cloud_flag is not False)
    if config.get("expanded_cloud_enabled") is False:
        use_cloud = False
    preprocess_meta["cloud_backend"] = cloud_backend
    preprocess_meta["glm53_in_expanded"] = cloud_backend == "glm53_flash_cloud"

    async def _local_answer(user_content: str, *, integrate: bool = False) -> str:
        msgs = ensure_aster_messages([{"role": "user", "content": user_content}])
        req_body = {"task_label": "grid_candidate_integrate"} if integrate else {}
        temp = (
            CANDIDATE_INTEGRATE_TEMP
            if integrate
            else resolve_substrate_temperature(route_class="chat", body=req_body)
        )
        sub = await substrate_chat(
            msgs,
            route_id=route_id,
            route_class="chat",
            max_tokens=budget,
            temperature=temp,
            request_body=req_body or None,
        )
        return str(sub.clean_content or "").strip()

    if not use_cloud:
        t_local = time.time()
        final = await _local_answer(task)
        timing["validate"] = int((time.time() - t_local) * 1000)
        timing["cloud"] = 0
        row = {
            "ts": time.time(),
            "route_id": route_id,
            "task_type": task_type,
            "substrate": "local",
            "budget": budget,
            "usage": {},
            "timing_ms": timing,
            "memory_snippets": len(memory_snippets),
            "sanitizer_hits": sanitizer_hits,
            "preprocess": preprocess_meta,
        }
        append_telemetry(telemetry_path, row)
        return {
            "final": final or "数据不足,暂无可用回答。",
            "substrate": "local",
            "usage": {"budget": budget},
            "provenance": {
                "candidate": "(未调用云端 substrate)",
                "envelope_summary": envelope_summary,
                "orchestrator": "8501",
                "timing_ms": timing,
            },
        }

    target = resolve_substrate_target(
        config,
        route_class="candidate",
        manual_backend_id=cloud_backend,
        body={"backend_id": cloud_backend},
    )
    execute_candidate = (
        glm53_backend.execute_candidate
        if cloud_backend == "glm53_flash_cloud"
        else glm52_backend.execute_candidate
    )
    default_model_name = (
        "glm-5.3-flash:cloud" if cloud_backend == "glm53_flash_cloud" else "glm-5.2:cloud"
    )

    t_cloud = time.time()
    cand_resp = await execute_candidate(
        request_id=route_id,
        prompt=prompt,
        endpoint=target.endpoint,
        model=target.model,
        task_label="grid_expanded",
        images=native_images or None,
        max_tokens=budget,
        temperature=0.3,
        timeout=float(config.get("expanded_timeout") or 300.0),
    )
    timing["cloud"] = int((time.time() - t_cloud) * 1000)

    if not cand_resp.ok:
        err = cand_resp.error or {}
        reason = err.get("reason") if isinstance(err, dict) else str(err or cand_resp.done_reason)
        err_sub = substrate_label_for(cloud_backend, suffix="_error")
        row = {
            "ts": time.time(),
            "route_id": route_id,
            "task_type": task_type,
            "substrate": err_sub,
            "budget": budget,
            "usage": {k: v for k, v in (cand_resp.usage or {}).items()
                      if k not in ("thinking", "reasoning_content")},
            "timing_ms": timing,
            "memory_snippets": len(memory_snippets),
            "sanitizer_hits": sanitizer_hits,
            "preprocess": preprocess_meta,
            "cloud_error": reason,
        }
        append_telemetry(telemetry_path, row)
        return {
            "final": f"cloud 不可用: {reason or f'{default_model_name} upstream error'}",
            "substrate": err_sub,
            "error": {"type": "cloud_unavailable", "reason": reason or "upstream_error"},
            "usage": dict(cand_resp.usage or {}),
            "provenance": {
                "candidate": "(cloud call failed)",
                "envelope_summary": envelope_summary,
                "orchestrator": "8501",
                "timing_ms": timing,
                "vl_warnings": vl_warnings,
                "cloud_backend": cloud_backend,
            },
        }

    candidate_text = str(cand_resp.content or "").strip()
    hit = impersonation_check(candidate_text)
    t_val = time.time()
    integrate_note = ""
    rejected = False
    # scout-/smoke 隔离 lane:跳过本地 Aster 接纳,直接以 cloud candidate 为终稿。
    skip_integrate = isolated_lane or bool(body.get("skip_aster_integrate"))
    cloud_sub = substrate_label_for(cloud_backend)
    if skip_integrate and not hit and candidate_text:
        final = candidate_text
        substrate = cloud_sub
        integrate_note = "aster_integrate_skipped:isolated_or_flag"
        preprocess_meta["aster_integrate"] = "skipped"
    else:
        try:
            if hit:
                final = await _local_answer(
                    f"{task}\n\n(云端 substrate 输出因越权/冒充被拒:{hit};请给出 Grid 最终回答并说明修正。)",
                )
                substrate = "local(candidate rejected)"
                rejected = True
            else:
                final = await _local_answer(
                    _validate_user_message(
                        task, candidate_text, cloud_backend=cloud_backend
                    ),
                    integrate=True,
                )
                substrate = cloud_sub
        except BaseException as exc:
            # 含 httpx.ReadTimeout / CancelledError:保留已成功的 cloud candidate
            integrate_note = f"aster_integrate_failsoft:{type(exc).__name__}"
            final = candidate_text or "数据不足,暂无可用回答。"
            substrate = substrate_label_for(cloud_backend, suffix="(integrate_failsoft)")
            rejected = False
            preprocess_meta["integrate_failsoft"] = str(exc)[:240]
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
    timing["validate"] = int((time.time() - t_val) * 1000)
    if integrate_note and integrate_note not in final:
        final = f"{final}\n\n({integrate_note})"
    if vl_warnings:
        note = " · ".join(dict.fromkeys(vl_warnings))
        if note and note not in final:
            final = f"{final}\n\n({note})"

    usage = dict(cand_resp.usage or {})
    usage["budget"] = budget
    row = {
        "ts": time.time(),
        "route_id": route_id,
        "task_type": task_type,
        "substrate": substrate,
        "budget": budget,
        "usage": {k: usage[k] for k in usage if k not in ("thinking", "reasoning_content")},
        "timing_ms": timing,
        "memory_snippets": len(memory_snippets),
        "sanitizer_hits": sanitizer_hits,
        "preprocess": preprocess_meta,
        "candidate_rejected": rejected,
        "vl_warnings": vl_warnings,
        "cloud_model": cand_resp.model or target.model,
        "cloud_backend": cloud_backend,
    }
    append_telemetry(telemetry_path, row)

    return {
        "final": final or "数据不足,暂无可用回答。",
        "substrate": substrate,
        "usage": usage,
        "provenance": {
            "candidate": candidate_text or "(empty)",
            "envelope_summary": envelope_summary,
            "orchestrator": "8501",
            "timing_ms": timing,
            "vl_warnings": vl_warnings,
            "cloud_backend": cloud_backend,
        },
    }
