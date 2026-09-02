"""Shared Ollama Cloud multi-turn executor for 8501 /task/cloud_chat."""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from code_task.backends.glm52_cloud import MIN_NUM_PREDICT, _extract_thinking, _thinking_meta, chat_payload
from code_task.candidate_contract import CandidateResponse
from code_task.glm52_pricing import enrich_glm52_usage
from code_task.glm53_cot_gate import (
    is_glm53_lane,
    resolve_glm53_visible_content,
    retry_messages,
    strip_think_tag,
)

BuildFn = Callable[[list[dict[str, Any]]], list[dict[str, str]]]
ToolExecFn = Callable[[str, dict[str, str]], str]

# P1: store 原文只读工具(text protocol)。延迟导入,避免无工具场景强依赖。
def _load_store_tools():
    try:
        from code_task.cloud_store_tools import (
            parse_tool_calls, strip_tool_calls, MAX_TOOL_CALLS_PER_ROUND,
        )
        return parse_tool_calls, strip_tool_calls, MAX_TOOL_CALLS_PER_ROUND
    except Exception:
        return None, None, 0

# Cloud think 在长记忆会话里常把 token 全吃掉 → content 空。策略写死在此，非一次性 patch。
# 适用于 glm52 / kimi_k25 / deepseek_v4(DeepSeek 默认只走 no_think) / glm53(Flash 一律 think 通道)。
MEMORY_TURN_SKIP_THINK = 3
MEMORY_CHAR_SKIP_THINK = 4000
# empty / length: drop oldest user/assistant pairs, then retry (auto refresh)
TRIM_PAIRS_ON_EMPTY = (0, 2, 4, 6, 8, 10, 12, 16, 24, 32)
# Soft pre-trim before first upstream call (chars across user/assistant turns)
SOFT_CONTEXT_CHARS = 28_000


def cloud_attempt_plan(
    ollama_messages: list[dict[str, str]],
    *,
    substrate: str | None = None,
    model: str | None = None,
) -> list[tuple[bool, str]]:
    """Return ordered (think, label) attempts for this payload."""
    sub = (substrate or "").strip().lower()
    model_l = (model or "").strip().lower()
    # DeepSeek v4-pro:cloud 与 scout 同规:默认 think 会空正文
    if sub == "deepseek_v4" or "deepseek" in model_l:
        return [(False, "no_think_deepseek")]
    # GLM-5.3 Flash + flagship: 强制 think。think=false 会把 CoT 写进 content。
    # 必须给够 num_predict,推理进 thinking 通道,content 才是回复。
    if "glm53" in sub or "glm-5.3" in model_l:
        return [(True, "think_glm53")]
    turns = [m for m in ollama_messages if m.get("role") in ("user", "assistant")]
    chars = sum(len(str(m.get("content") or "")) for m in turns)
    if len(turns) >= MEMORY_TURN_SKIP_THINK or chars >= MEMORY_CHAR_SKIP_THINK:
        return [(False, "no_think_memory")]
    return [(True, "think"), (False, "no_think_fallback")]


def _parse_ollama_body(body: dict[str, Any], *, model: str) -> tuple[str, str, str, dict[str, Any], str]:
    message = body.get("message") if isinstance(body.get("message"), dict) else {}
    thinking = _extract_thinking(message, body)
    content = str(message.get("content") or "").strip()
    done = str(body.get("done_reason") or message.get("done_reason") or "stop")
    upstream_model = str(body.get("model") or message.get("model") or model).strip()
    raw_usage = dict(body.get("usage") or {})
    for key in ("prompt_eval_count", "eval_count"):
        if key in body and key not in raw_usage:
            raw_usage[key] = body[key]
    return content, done, upstream_model, raw_usage, thinking


def _merge_usage(merged: dict[str, Any], raw: dict[str, Any]) -> None:
    for key, val in raw.items():
        if key not in merged:
            merged[key] = val
        elif isinstance(val, (int, float)) and isinstance(merged.get(key), (int, float)):
            merged[key] = merged[key] + val


def _normalize_b64_images(images: Any) -> list[str]:
    """Ollama chat message.images = list of raw base64 strings."""
    if not images:
        return []
    if not isinstance(images, list):
        return []
    out: list[str] = []
    for item in images:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict):
            b64 = str(item.get("base64") or item.get("data") or "").strip()
            if b64:
                out.append(b64)
        if len(out) >= 6:
            break
    return out


def _attach_images_last_user(
    ollama_messages: list[dict[str, Any]], images: Any
) -> list[dict[str, Any]]:
    b64s = _normalize_b64_images(images)
    if not b64s:
        return ollama_messages
    out = [dict(m) for m in ollama_messages]
    for i in range(len(out) - 1, -1, -1):
        if out[i].get("role") == "user":
            out[i]["images"] = b64s
            return out
    return out


def _dial_chars(messages: list[dict[str, Any]]) -> int:
    return sum(
        len(str(m.get("content") or ""))
        for m in (messages or [])
        if isinstance(m, dict) and m.get("role") in ("user", "assistant")
    )


def _pretrim_messages(
    messages: list[dict[str, Any]], *, soft_chars: int = SOFT_CONTEXT_CHARS
) -> tuple[list[dict[str, Any]], int]:
    """Drop oldest dial turns until under soft char budget. Keeps trailing user."""
    msgs = [dict(m) for m in (messages or []) if isinstance(m, dict)]
    dropped = 0
    while len(msgs) > 1 and _dial_chars(msgs) > soft_chars:
        # drop first user/assistant (not system — builders re-inject system)
        if msgs[0].get("role") == "system":
            if len(msgs) < 3:
                break
            msgs = [msgs[0], *msgs[3:]] if msgs[1].get("role") in ("user", "assistant") else msgs[1:]
            dropped += 2
            continue
        msgs = msgs[1:]
        dropped += 1
    return msgs, dropped


async def execute_cloud_chat(
    *,
    request_id: str,
    messages: list[dict[str, Any]],
    endpoint: str,
    model: str,
    build_messages: BuildFn,
    source: str,
    images: Any = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    timeout: float = 300.0,
    substrate: str | None = None,
    tool_executor: ToolExecFn | None = None,
    tool_declaration: str | None = None,
) -> CandidateResponse:
    sub = (substrate or "").strip().lower()
    # Pixels never enter GLM/DeepSeek chat; M3 / Kimi VL already transcribed.
    if images:
        return CandidateResponse(
            request_id=request_id,
            ok=False,
            done_reason="input_rejected",
            source=source,
            model=model,
            error={
                "type": "input_scope",
                "reason": "cloud_chat is text-only; GLM uses M3 eyes, DeepSeek uses Kimi VL",
            },
        )

    predict = max(int(max_tokens), MIN_NUM_PREDICT)
    started = time.time()
    last_done = "stop"
    last_model = model
    last_meta = _thinking_meta("")
    merged_usage: dict[str, Any] = {}
    cot_blocked = False
    messages, pre_dropped = _pretrim_messages(list(messages or []))

    # P1: store 原文工具(text protocol)
    parse_tool_calls, strip_tool_calls, _MAX_TOOL_CALLS = _load_store_tools()
    tool_rounds_done = 0

    async def _one_post(client, ollama_messages, think, *, temp=None, predict_override=None):
        # 单次上游 POST → (content, done, upstream_model, raw_usage, thinking) 或抛
        r = await client.post(
            endpoint,
            json=chat_payload(
                ollama_messages, model=model, max_tokens=predict_override or predict,
                temperature=float(temp if temp is not None else temperature), think=think,
            ),
        )
        r.raise_for_status()
        body = r.json()
        content, done, upstream_model, raw_usage, thinking = _parse_ollama_body(body, model=model)
        _merge_usage(merged_usage, raw_usage)
        return content, done, upstream_model, thinking

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            for trim in TRIM_PAIRS_ON_EMPTY:
                subset = messages[trim:] if trim else messages
                if not subset:
                    break
                try:
                    ollama_messages = build_messages(subset)
                except ValueError:
                    continue
                if images and sub == "glm53":
                    ollama_messages = _attach_images_last_user(ollama_messages, images)
                # P1: 工具声明注入到 build_messages 之后(避免被 _extract_memory_systems 丢弃)
                if tool_declaration and parse_tool_calls is not None:
                    ollama_messages = [{"role": "system", "content": tool_declaration}] + list(ollama_messages)
                plan = cloud_attempt_plan(
                    ollama_messages, substrate=substrate, model=model
                )
                for think, label in plan:
                    content, done, upstream_model, thinking = await _one_post(client, ollama_messages, think)
                    last_done, last_model = done, upstream_model
                    last_meta = _thinking_meta(thinking)
                    if is_glm53_lane(substrate, model) and content:
                        first_content = content
                        content, cot_action = resolve_glm53_visible_content(
                            first_content, retried=False
                        )
                        if cot_action == "retry_needed":
                            try:
                                retry_body, done_r, upstream_r, thinking_r = await _one_post(
                                    client, retry_messages(ollama_messages), True, temp=0.3
                                )
                                last_done, last_model = done_r, upstream_r
                                last_meta = _thinking_meta(thinking_r)
                            except Exception:
                                retry_body = ""
                            content, cot_action = resolve_glm53_visible_content(
                                first_content, retry_body, retried=True
                            )
                        if cot_action == "retry":
                            label = "think_glm53_cot_retry"
                        elif cot_action == "strip":
                            label = "think_glm53_cot_strip"
                        elif cot_action == "block":
                            cot_blocked = True
                            last_done = "cot_in_content"
                            content = ""
                            break
                    if content:
                        # P1: 工具调用循环 —— GLM 发工具调用 → 执行 → 喂回 → 再问
                        if tool_executor is not None and parse_tool_calls is not None and strip_tool_calls is not None:
                            cur_msgs = list(ollama_messages)
                            cur_content = content
                            tool_rounds_done = 0
                            while tool_rounds_done < _MAX_TOOL_CALLS:
                                calls = parse_tool_calls(cur_content)
                                if not calls:
                                    break
                                results: list[str] = []
                                for name, args in calls[:_MAX_TOOL_CALLS - tool_rounds_done]:
                                    try:
                                        res = tool_executor(name, args)
                                    except Exception as exc:  # 工具失败不杀整轮
                                        res = "工具 %s 错误: %s" % (name, str(exc)[:200])
                                    results.append("<<tool_result for %s>>\n%s\n<<end_tool_result>>" % (name, res))
                                    tool_rounds_done += 1
                                if not results:
                                    break
                                cur_msgs = cur_msgs + [
                                    {"role": "assistant", "content": cur_content},
                                    {"role": "user", "content": "\n\n".join(results) + "\n\n基于以上原文作答,别再发工具调用除非确实还需要查。"},
                                ]
                                try:
                                    # 工具循环=贴原文的长回复 → glm53 给 12288(聊天 8192 / 工具 12288)
                                    tool_predict = 12288 if is_glm53_lane(substrate, model) else None
                                    cur_content, done, upstream_model, thinking = await _one_post(
                                        client, cur_msgs, False, predict_override=tool_predict)
                                    last_done, last_model = done, upstream_model
                                    last_meta = _thinking_meta(thinking)
                                except Exception:
                                    break
                                if not cur_content:
                                    break
                                # glm53 工具循环用 think=False → CoT 会写进 content,补剥
                                if is_glm53_lane(substrate, model):
                                    cur_content = strip_think_tag(cur_content)
                            content = strip_tool_calls(cur_content)
                        usage = enrich_glm52_usage(merged_usage)
                        usage["latency_ms"] = int((time.time() - started) * 1000)
                        usage["backend_id"] = source
                        usage["ollama_cloud"] = True
                        usage["memory_turns"] = max(0, len(ollama_messages) - 1)
                        usage["cloud_policy"] = label
                        if trim:
                            usage["cloud_trim_dropped"] = trim
                        if pre_dropped:
                            usage["cloud_pretrim_dropped"] = pre_dropped
                        if tool_rounds_done:
                            usage["tool_rounds"] = tool_rounds_done
                        return CandidateResponse(
                            request_id=request_id,
                            ok=True,
                            content=content,
                            done_reason=last_done or done,
                            source=source,
                            usage=usage,
                            thinking_meta=last_meta,
                            model=last_model or upstream_model,
                        )
                if cot_blocked:
                    break
    except httpx.HTTPStatusError as exc:
        detail = str(exc)[:400]
        try:
            err_body = exc.response.json()
            if isinstance(err_body, dict) and err_body.get("error"):
                detail = str(err_body["error"])[:400]
        except Exception:
            pass
        return CandidateResponse(
            request_id=request_id,
            ok=False,
            done_reason="upstream_error",
            source=source,
            model=model,
            error={"type": type(exc).__name__, "reason": detail},
            usage={"latency_ms": int((time.time() - started) * 1000)},
        )

    usage = enrich_glm52_usage(merged_usage)
    usage["latency_ms"] = int((time.time() - started) * 1000)
    usage["backend_id"] = source
    usage["ollama_cloud"] = True
    usage["memory_turns"] = max(0, len(messages) - 1)
    err_type = "cot_in_content" if last_done == "cot_in_content" else "empty_content"
    err_reason = (
        "GLM-5.3 Flash 把推理写进 content · 8501 已 think 通道 + 重试 + 截断 · 仍是 CoT 已拦截未下发"
        if err_type == "cot_in_content"
        else (
            "Cloud 上游 content 空(think 占满或 length) · 8501 已自动: "
            "单条截断→软裁窗→no_think→裁旧轮重试 · 仍失败请稍后再发"
        )
    )
    return CandidateResponse(
        request_id=request_id,
        ok=False,
        content="",
        done_reason=last_done or "empty_content",
        source=source,
        model=last_model,
        usage=usage,
        thinking_meta=last_meta,
        error={
            "type": err_type,
            "reason": err_reason,
        },
    )
