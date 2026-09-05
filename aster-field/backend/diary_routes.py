"""日记路由 — 写 POST /diary; 读 GET /diary(需解锁 token); 设置 POST /diary/pin。"""
from fastapi import Request
from fastapi.responses import JSONResponse
from .diary_store import add, all_entries, verify
from .diary_pin import pin_is_set, set_pin, unlock, check_token
from .diary_reply import DiaryReplyStore
from .diary_guard import require_scheduler_writer, reject_probe_text
from . import grid_diary_client as gw

def _merge_replies(entry: dict) -> list[dict]:
    """本地 Lyra 回信 + 8501 grid_store 往来（Grid ack）合并显示。"""
    local = _replies.thread(int(entry["id"]))["replies"]
    try:
        remote = gw.replies_for_date(gw._entry_date(entry.get("ts", "")))
    except Exception:
        remote = []
    seen: set[tuple[str, str, str]] = set()
    merged: list[dict] = []

    def add(row: dict) -> None:
        author = row.get("author") or "lyra"
        text = (row.get("text") or "").strip()
        ts = str(row.get("ts") or "")
        if not text:
            return
        key = (author, ts[:19], text[:120])
        if key in seen:
            return
        seen.add(key)
        merged.append({
            "id": row.get("id"),
            "author": author,
            "text": text,
            "ts": ts,
        })

    for r in local:
        add(r)
    for r in remote:
        add(r)
    merged.sort(key=lambda r: r.get("ts") or "")
    return merged


_replies = DiaryReplyStore()


def _token(req: Request) -> str | None:
    auth = req.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return req.headers.get("x-diary-token")


def _entry_by_id(entry_id: int) -> dict | None:
    for e in all_entries():
        if e["id"] == entry_id:
            return e
    return None


def register_diary_routes(app):
    @app.get("/diary/settings")
    async def diary_settings():
        return JSONResponse({"pin_set": pin_is_set()})

    @app.post("/diary/pin")
    async def diary_pin_set(req: Request):
        body = await req.json()
        return JSONResponse(set_pin(body.get("pin", ""), body.get("old_pin")))

    @app.post("/diary/unlock")
    async def diary_unlock(req: Request):
        body = await req.json()
        return JSONResponse(unlock(body.get("pin", "")))

    @app.post("/diary")
    async def diary_write(req: Request):
        try:
            require_scheduler_writer(req.headers.get("x-diary-writer"))
        except PermissionError as ex:
            return JSONResponse({"error": str(ex)}, status_code=403)
        body = await req.json()
        try:
            reject_probe_text((body.get("text") or ""), what="diary entry")
        except ValueError as ex:
            return JSONResponse({"error": str(ex)}, status_code=422)
        return JSONResponse(add(body.get("text", "")))

    @app.get("/diary/integrity")
    async def diary_integrity():
        return JSONResponse({"integrity": verify()})

    @app.get("/diary/memory")
    async def diary_memory(req: Request, days: int = 7):
        if not check_token(_token(req)):
            return JSONResponse({"error": "需要密码", "pin_required": True}, status_code=401)
        return JSONResponse(_replies.memory_context(days))

    @app.post("/diary/reply")
    async def diary_reply_write(req: Request):
        if not check_token(_token(req)):
            return JSONResponse({"error": "需要密码", "pin_required": True}, status_code=401)
        body = await req.json()
        entry_id = body.get("entry_id")
        text = (body.get("text") or "").strip()
        if not isinstance(entry_id, int) or not text:
            return JSONResponse({"error": "entry_id(int) and text required"}, status_code=422)
        try:
            reject_probe_text(text, what="reply")
            out = _replies.add_lyra_reply(entry_id, text)
        except KeyError as ex:
            return JSONResponse({"error": str(ex)}, status_code=404)
        except ValueError as ex:
            return JSONResponse({"error": str(ex)}, status_code=422)
        except PermissionError as ex:
            return JSONResponse({"error": str(ex)}, status_code=403)
        entry = _entry_by_id(entry_id)
        grid_sync = {"ok": False, "error": None, "grid_reply_id": None}
        if entry:
            try:
                grid_sync["grid_reply_id"] = gw.post_reply_for_entry(entry, text).get("id")
                grid_sync["ok"] = True
            except Exception as ex:
                grid_sync["error"] = str(ex)
        return JSONResponse({**out, "grid_sync": grid_sync})

    @app.get("/diary")
    async def diary_read(req: Request):
        if not check_token(_token(req)):
            return JSONResponse({"error": "需要密码", "pin_required": True}, status_code=401)
        entries = all_entries()
        for e in entries:
            e["replies"] = _merge_replies(e)
        target = gw.reply_target_entry_id(entries)
        return JSONResponse({
            "entries": entries,
            "integrity": verify(),
            "reply_integrity": _replies.verify(),
            "reply_target_entry_id": target if target is not None else (entries[-1]["id"] if entries else None),
        })
