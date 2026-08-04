import asyncio, json, os, time
import httpx, uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from .config import CFG
from .state_bus import BUS
from .relay import derive_event, coherence_proxy
from .telemetry import garden_poller, gateway_poller
from .diary_routes import register_diary_routes
from .task_route import classify_task, max_tokens_for, is_json_task
from .json_artifact import parse_json_artifact
from field_lane.schema import COMPILE_SEMANTICS_PARSE_ONLY, SCHEMA_LOOSE
from . import chat_memory
from . import field_distill

import sys
from pathlib import Path
from typing import Any

_GSR = Path(__file__).resolve().parents[2] / "grid-sovereign-runtime"
if str(_GSR) not in sys.path:
    sys.path.insert(0, str(_GSR))
from gateway.grid_store import log_store_auth_banner, store_auth_status  # noqa: E402

app = FastAPI(title="aster-field")
register_diary_routes(app)


class _NoCacheUiMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.endswith(".html") or path.startswith("/assets/"):
            response.headers["Cache-Control"] = "no-store, must-revalidate"
        return response


app.add_middleware(_NoCacheUiMiddleware)

CONTINUE_USER = (
    "Continue exactly where you left off. Do not repeat prior content. "
    "Complete the JSON output only."
)


def _done_payload(*, served, finish, full, task, budget, part_idx, merged) -> dict:
    truncated = finish == "length"
    text = "".join(full)
    out = {
        "done": True,
        "served_by": served,
        "finish_reason": finish,
        "truncated": truncated,
        "transport_truncated": truncated,
        "text": text,
        "task_type": task,
        "max_tokens": budget,
        "continuation_part": part_idx,
    }
    if is_json_task(task):
        parsed = parse_json_artifact(merged if merged is not None else text)
        out["artifact"] = parsed
        out["merged_json_valid"] = parsed.get("merged_json_valid", False)
        out["schema"] = parsed.get("schema", SCHEMA_LOOSE)
        out["compile_semantics"] = parsed.get("compile_semantics", COMPILE_SEMANTICS_PARSE_ONLY)
        if not parsed.get("ok"):
            out["status"] = parsed.get("status", "INCOMPLETE_ARTIFACT")
        elif finish == "stop" or parsed.get("merged_json_valid"):
            out["status"] = "PASS"
    return out


def _turn_complete(done: dict, task: str) -> bool:
    if done.get("merged_json_valid"):
        return True
    if done.get("finish_reason") == "stop":
        return True
    if is_json_task(task):
        return False
    return not done.get("truncated")


def _gateway_base() -> str:
    return CFG["gateway"].rsplit("/v1/", 1)[0].rstrip("/")


async def _resolve_chat_context(body: dict[str, Any]) -> dict[str, Any] | JSONResponse:
    msg = (body.get("message") or "").strip()
    image = body.get("image")
    has_image = isinstance(image, str) and image.startswith("data:image/")
    if not msg and not body.get("continue") and not has_image:
        return JSONResponse({"error": "empty message"}, status_code=400)
    seed = msg or (body.get("original_message") or "").strip() or ("[图]" if has_image else "")
    task = classify_task(seed, body.get("task_type"))
    if has_image and task != "chat":
        task = "chat"
    budget = max_tokens_for(task)
    part_idx = int(body.get("continuation_part") or 0)
    use_mem = chat_memory.uses_memory(task)
    mem_user = chat_memory.memory_user_text(msg, has_image=has_image)
    history: list[dict[str, str]] = []
    if use_mem:
        history = await asyncio.to_thread(chat_memory.fetch_history, task=task)
        if part_idx > 0 or body.get("continue"):
            orig = chat_memory.memory_user_text(
                (body.get("original_message") or seed).strip(),
                has_image=bool(body.get("had_image")),
            )
            if history and history[-1].get("role") == "user" and history[-1].get("content") == orig:
                history = history[:-1]

    gateway_messages = chat_memory.build_gateway_messages(
        body, msg or ("分析这张图" if has_image else ""), history if use_mem else None,
        continue_user=CONTINUE_USER,
        image=image if has_image and part_idx == 0 and not body.get("continue") else None,
    )
    session_meta: dict = {}
    if use_mem and part_idx == 0:
        root = Path(__file__).resolve().parents[2] / "grid-sovereign-runtime"
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from field_lane.method_cards import inject_messages

        gateway_messages, session_meta = inject_messages(
            gateway_messages,
            task=task,
            instruction=(body.get("original_message") or seed).strip(),
            node_id=chat_memory.node_for_task(task),
        )
    use_model = CFG["vl_model"] if has_image else CFG["gateway_model"]
    return {
        "msg": msg,
        "image": image,
        "has_image": has_image,
        "seed": seed,
        "task": task,
        "budget": budget,
        "part_idx": part_idx,
        "use_mem": use_mem,
        "mem_user": mem_user,
        "gateway_messages": gateway_messages,
        "session_meta": session_meta,
        "use_model": use_model,
        "body": body,
    }


@app.post("/chat/prepare-verification")
async def chat_prepare_verification(req: Request):
    body = await req.json()
    ctx = await _resolve_chat_context(body)
    if isinstance(ctx, JSONResponse):
        return ctx
    if ctx["use_model"] != CFG["gateway_model"]:
        return {"skip": True, "reason": "non-aster model", "model": ctx["use_model"]}
    return {
        "model": ctx["use_model"],
        "messages": ctx["gateway_messages"],
        "grid_gateway_base": _gateway_base(),
    }


@app.on_event("startup")
async def _start():
    log_store_auth_banner()
    asyncio.create_task(garden_poller())
    asyncio.create_task(gateway_poller())

@app.get("/state")
async def state_sse():
    q: asyncio.Queue = asyncio.Queue(maxsize=64)
    BUS.subs.add(q)
    async def gen():
        try:
            yield f"data: {json.dumps(BUS.snapshot)}\n\n"
            while True:
                yield f"data: {json.dumps(await q.get(), ensure_ascii=False)}\n\n"
        finally:
            BUS.subs.discard(q)
    return StreamingResponse(gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.get("/chat/memory")
async def chat_memory_status():
    purge = await asyncio.to_thread(chat_memory.maybe_purge_epoch)
    lanes = await asyncio.to_thread(chat_memory.fetch_all_lanes)
    return {
        **chat_memory.memory_status(),
        "lanes": {k: len(v) for k, v in lanes.items()},
        "message_count": sum(len(v) for v in lanes.values()),
        "store_sync": purge.get("purged") is not False or "error" not in purge,
        "last_purge": purge,
        "distill_enabled": field_distill._enabled(),
    }

@app.get("/chat/history")
async def chat_history(lane: str | None = None):
    if lane in ("chat", "compile", "compile_json"):
        task = "compile_json" if lane == "compile" else "chat"
        rows = await asyncio.to_thread(chat_memory.fetch_history, task=task)
        return {
            "lane": lane,
            "node_id": chat_memory.node_for_task(task),
            "messages": rows,
            **chat_memory.memory_status(),
        }
    lanes = await asyncio.to_thread(chat_memory.fetch_all_lanes)
    return {
        "lanes": {
            "chat": {"node_id": chat_memory.NODE_CHAT, "messages": lanes["chat"]},
            "compile": {"node_id": chat_memory.NODE_COMPILE, "messages": lanes["compile"]},
        },
        **chat_memory.memory_status(),
    }


async def _after_turn_saved(
    *,
    instruction: str,
    merged: str,
    task: str,
    test: bool | None = None,
) -> None:
    node_id = chat_memory.node_for_task(task)
    schema = SCHEMA_LOOSE if is_json_task(task) else None
    compile_semantics = COMPILE_SEMANTICS_PARSE_ONLY if is_json_task(task) else None
    await asyncio.to_thread(
        field_distill.schedule_after_turn,
        instruction,
        merged,
        task=task,
        node_id=node_id,
        persona="8790",
        client="field8790",
        schema=schema,
        compile_semantics=compile_semantics,
        test=test,
    )


@app.post("/chat/coach")
async def chat_coach(req: Request):
    """Fable coach zone — sync run returns record + cost + gate."""
    body = await req.json()
    instruction = str(body.get("instruction") or "").strip()
    draft = str(body.get("draft") or "").strip()
    if not draft:
        return JSONResponse({"error": "draft required"}, status_code=400)
    task = classify_task(instruction or draft, body.get("task_type"))
    node_id = chat_memory.node_for_task(task)
    allow_draft = bool(body.get("allow_draft"))
    compile_semantics = body.get("compile_semantics")
    test = body.get("test")

    if body.get("async"):
        await asyncio.to_thread(
            field_distill.schedule_coach,
            instruction or draft,
            draft,
            task=task,
            node_id=node_id,
            persona="8790-coach",
            client="field8790",
            compile_semantics=str(compile_semantics).strip() if compile_semantics else None,
            allow_draft=allow_draft,
            test=bool(test) if test is not None else None,
        )
        return {
            "queued": True,
            "coach": True,
            "task": task,
            "node_id": node_id,
            "auto_eligible": field_distill.should_distill(task),
        }

    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "grid-sovereign-runtime"
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from field_lane.distill_api import run_coach_sync

    result = await asyncio.to_thread(
        run_coach_sync,
        instruction=instruction or draft,
        draft=draft,
        task=task,
        node_id=node_id,
        client="field8790",
        persona="8790-coach",
        force=True,
        compile_semantics=str(compile_semantics).strip() if compile_semantics else None,
        allow_draft=allow_draft,
        test=bool(test) if test is not None else None,
    )
    return result


def _distill_root():
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "grid-sovereign-runtime"
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


@app.get("/distill/queue")
async def distill_queue(status: str = "pending", date: str | None = None, limit: int = 50):
    _distill_root()
    from field_lane.distill_api import list_queue

    return {"rows": await asyncio.to_thread(list_queue, status=status, on_date=date, limit=limit)}


@app.get("/distill/record/{record_id}")
async def distill_record(record_id: str):
    _distill_root()
    from field_lane.distill_api import get_record_detail

    row = await asyncio.to_thread(get_record_detail, record_id)
    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)
    return row


@app.get("/distill/recent")
async def distill_recent(limit: int = 10, date: str | None = None):
    _distill_root()
    from field_lane.distill_api import recent_records

    return {"records": await asyncio.to_thread(recent_records, limit=limit, on_date=date)}


@app.get("/distill/latest_compile")
async def distill_latest_compile():
    _distill_root()
    from field_lane.distill_api import latest_compile_pair

    return await asyncio.to_thread(latest_compile_pair)


@app.get("/distill/stats")
async def distill_stats(date: str | None = None):
    _distill_root()
    from field_lane.review_state import stats_summary

    return await asyncio.to_thread(stats_summary, on_date=date)


@app.post("/distill/review")
async def distill_review(req: Request):
    body = await req.json()
    record_id = str(body.get("record_id") or "").strip()
    status = str(body.get("status") or "").strip()
    reason = str(body.get("reason") or "").strip()
    via = str(body.get("via") or "tab3")
    if not record_id or not status:
        return JSONResponse({"error": "record_id and status required"}, status_code=400)
    _distill_root()
    from field_lane.distill_api import post_review

    try:
        return await asyncio.to_thread(post_review, record_id, status, reason=reason, via=via)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    except KeyError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)

@app.post("/chat")
async def chat(req: Request):
    body = await req.json()
    ctx = await _resolve_chat_context(body)
    if isinstance(ctx, JSONResponse):
        return ctx
    msg = ctx["msg"]
    has_image = ctx["has_image"]
    image = ctx["image"]
    seed = ctx["seed"]
    task = ctx["task"]
    budget = ctx["budget"]
    part_idx = ctx["part_idx"]
    use_mem = ctx["use_mem"]
    mem_user = ctx["mem_user"]
    gateway_messages = ctx["gateway_messages"]
    session_meta = ctx["session_meta"]
    use_model = ctx["use_model"]
    payload = {
        "model": use_model,
        "stream": True,
        "max_tokens": budget,
        "temperature": CFG["temperature"],
        "messages": gateway_messages,
    }
    # 门保持摘除。8790→8501 外发：进程内 attach_grid_verification(禁止 HTTP 要签)
    _wb = _GSR / "workbench"
    if str(_wb) not in sys.path:
        sys.path.insert(0, str(_wb))
    from gateway_verify_proxy import (  # noqa: E402
        DEFAULT_GATEWAY,
        SIGNER_ID,
        _ensure_key_env,
        attach_grid_verification,
    )
    _gw_timeout = 15.0
    if use_model == CFG["gateway_model"]:
        try:
            _ensure_key_env()
            payload = attach_grid_verification(
                payload,
                gateway_base=_gateway_base() or DEFAULT_GATEWAY,
                signer_id=SIGNER_ID,
            )
        except Exception as exc:
            return JSONResponse(
                {"error": f"grid_verification sign failed: {exc}"},
                status_code=503,
            )
    # 写序:persistUser(+[文件]) → 调模型 → persistAssistant
    user_persisted = False
    if use_mem and part_idx == 0 and not body.get("continue") and mem_user:
        att = "image data:image/* (8790 attachment)" if has_image else None
        user_persisted = await asyncio.to_thread(
            chat_memory.append_user, mem_user, task=task,
            surface="8790", attachment_note=att,
        )
    await BUS.pub(state="thinking", tokens=0)

    async def gen():
        state, n_tok, full, finish, served, t0 = "thinking", 0, [], None, None, time.time()
        contract_flag = None
        gw_http = None
        gw_detail = None
        try:
            async with httpx.AsyncClient(timeout=_gw_timeout) as cli:
                async with cli.stream("POST", CFG["gateway"], json=payload) as r:
                    gw_http = r.status_code
                    if r.status_code >= 400:
                        raw = (await r.aread()).decode("utf-8", "replace")[:300]
                        gw_detail = raw or r.reason_phrase or "empty body"
                    else:
                        async for line in r.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                            except Exception:
                                continue
                            ev = derive_event(chunk, state)
                            served = ev["served_by"] or served
                            finish = ev["finish"] or finish
                            if ev.get("contract_flag"):
                                contract_flag = ev["contract_flag"]
                            if ev["state"] != state:
                                state = ev["state"]
                                await BUS.pub(state=state)
                            if ev["reasoning"]:
                                n_tok += 1
                                if n_tok % 8 == 0:
                                    await BUS.pub(state=state, tokens=n_tok)
                            if ev["token"]:
                                full.append(ev["token"]); n_tok += 1
                                await BUS.pub(state="output", tokens=n_tok)
                                yield f"data: {json.dumps({'token': ev['token']}, ensure_ascii=False)}\n\n"
            prior = body.get("prior_text") or ""
            merged = prior + "".join(full) if body.get("continue") else "".join(full)
            garden = BUS.snapshot["coherence"] if BUS.snapshot["links"].get("garden") else None
            coh = coherence_proxy(finish, bool(full), time.time() - t0, garden)
            await BUS.pub(state="idle", coherence=coh)
            done = _done_payload(
                served=served, finish=finish, full=full, task=task, budget=budget,
                part_idx=part_idx, merged=merged,
            )
            if contract_flag:
                done["contract_flag"] = contract_flag
            elif "contract_flag: subject_inversion" in done.get("text", ""):
                done["contract_flag"] = "subject_inversion"
            # served_by=null 空 done：如实文案，禁止静默空屏
            if not (done.get("text") or "").strip() and not served:
                reason = gw_detail or "无正文"
                status = gw_http if gw_http is not None else "?"
                msg = f"网关拒答 · HTTP {status} · {reason}"
                done["text"] = msg
                done["error"] = msg
                done["finish_reason"] = "gateway_rejected"
            if use_mem and _turn_complete(done, task) and merged.strip():
                # 用户轮已在 prepare 阶段落库;此处只落 assistant
                await asyncio.to_thread(
                    chat_memory.append_assistant, merged, task=task, surface="8790",
                )
                done["memory_saved"] = True
                done["memory_node"] = chat_memory.node_for_task(task)
                done["user_persisted"] = bool(user_persisted)
                asyncio.create_task(
                    _after_turn_saved(
                        instruction=(body.get("original_message") or seed).strip(),
                        merged=merged,
                        task=task,
                    )
                )
            if has_image:
                done["vision"] = True
                done["vl_model"] = use_model
            if session_meta:
                done["session_seed"] = session_meta.get("session_seed")
                done["method_cards_used"] = session_meta.get("method_cards_used")
            yield "data: " + json.dumps(done, ensure_ascii=False) + "\n\n"
        except httpx.TimeoutException:
            await BUS.pub(state="error")
            yield f"data: {json.dumps({'error': '网关超时', 'done': True, 'text': '网关超时', 'served_by': None}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.6)
            await BUS.pub(state="idle")
        except Exception as e:
            await BUS.pub(state="error")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            await asyncio.sleep(0.6)
            await BUS.pub(state="idle")
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": "aster-field",
        "links": BUS.snapshot["links"],
        "grid_gateway_base": _gateway_base(),
        "task_budgets": CFG["task_budgets"],
        "vl_model": CFG["vl_model"],
        "chat_memory": chat_memory.memory_status(),
        "store_auth": store_auth_status(),
    }

if os.path.isdir(CFG["dist"]):
    app.mount("/", StaticFiles(directory=CFG["dist"], html=True), name="dist")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=CFG["port"], log_level="warning")
