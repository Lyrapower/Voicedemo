"""日记路由 — 写 POST /diary; 读 GET /diary(需解锁 token); 设置 POST /diary/pin。"""
from fastapi import Request
from fastapi.responses import JSONResponse
from .diary_store import add, all_entries, verify
from .diary_pin import pin_is_set, set_pin, unlock, check_token

def _token(req: Request) -> str | None:
    auth = req.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return req.headers.get("x-diary-token")


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
        body = await req.json()
        return JSONResponse(add(body.get("text", "")))

    @app.get("/diary/integrity")
    async def diary_integrity():
        """仅 hash 链校验,不返回正文 — 供 launchd --verify 使用。"""
        return JSONResponse({"integrity": verify()})

    @app.get("/diary")
    async def diary_read(req: Request):
        if not check_token(_token(req)):
            return JSONResponse({"error": "需要密码", "pin_required": True}, status_code=401)
        return JSONResponse({"entries": all_entries(), "integrity": verify()})
