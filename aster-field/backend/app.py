import asyncio, json, os, time
import httpx, uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .config import CFG
from .state_bus import BUS
from .relay import derive_event, coherence_proxy
from .telemetry import garden_poller, gateway_poller
from .diary_routes import register_diary_routes
from .task_route import classify_task, max_tokens_for, is_json_task
from .json_artifact import parse_json_artifact

app = FastAPI(title="aster-field")
register_diary_routes(app)

CONTINUE_USER = (
    "Continue exactly where you left off. Do not repeat prior content. "
    "Complete the JSON output only."
)


def _build_messages(body: dict, msg: str) -> list[dict]:
    if body.get("continue") and body.get("prior_text"):
        orig = (body.get("original_message") or msg).strip()
        return [
            {"role": "user", "content": orig},
            {"role": "assistant", "content": body["prior_text"]},
            {"role": "user", "content": CONTINUE_USER},
        ]
    return [{"role": "user", "content": msg}]


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
        if not parsed.get("ok"):
            out["status"] = parsed.get("status", "INCOMPLETE_ARTIFACT")
        elif finish == "stop" or parsed.get("merged_json_valid"):
            out["status"] = "PASS"
    return out


@app.on_event("startup")
async def _start():
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

@app.post("/chat")
async def chat(req: Request):
    body = await req.json()
    msg = (body.get("message") or "").strip()
    if not msg and not body.get("continue"):
        return JSONResponse({"error": "empty message"}, status_code=400)
    seed = msg or (body.get("original_message") or "").strip()
    task = classify_task(seed, body.get("task_type"))
    budget = max_tokens_for(task)
    part_idx = int(body.get("continuation_part") or 0)
    payload = {
        "model": CFG["gateway_model"],
        "stream": True,
        "max_tokens": budget,
        "temperature": CFG["temperature"],
        "messages": _build_messages(body, msg),
    }
    await BUS.pub(state="thinking", tokens=0)

    async def gen():
        state, n_tok, full, finish, served, t0 = "thinking", 0, [], None, None, time.time()
        contract_flag = None
        try:
            async with httpx.AsyncClient(timeout=300) as cli:
                async with cli.stream("POST", CFG["gateway"], json=payload) as r:
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
            yield "data: " + json.dumps(done, ensure_ascii=False) + "\n\n"
        except Exception as e:
            await BUS.pub(state="error")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            await asyncio.sleep(0.6)
            await BUS.pub(state="idle")
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})

@app.get("/health")
async def health():
    return {"ok": True, "service": "aster-field", "links": BUS.snapshot["links"],
            "task_budgets": CFG["task_budgets"]}

if os.path.isdir(CFG["dist"]):
    app.mount("/", StaticFiles(directory=CFG["dist"], html=True), name="dist")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=CFG["port"], log_level="warning")
