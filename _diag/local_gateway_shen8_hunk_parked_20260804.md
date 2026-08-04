# 审8 暂存 · 等 Lyra 拍板 · 拍板前勿改 local_gateway.py
# 工作区已含下列片段(相对运行中文件);整文件相对 HEAD 另有巨量既有漂移,勿整文件提交

## DEFAULT_STORE_DB import @ ~L777
```

# 真库唯一常量:grid_mem.DEFAULT_STORE_DB(禁止 data/ 软链)
from grid_mem import DEFAULT_STORE_DB as _GRID_STORE_DB  # noqa: E402
from diary_reply import build_diary_router  # noqa: E402
from grid_store import GridStore, build_router as build_grid_store_router, log_store_auth_banner, store_auth_status  # noqa: E402
from watcher_snapshot import build_router as build_watcher_snapshot_router  # noqa: E402

app.include_router(build_grid_store_router(_GRID_STORE_DB))
```

## cloud_chat status mapping @ ~L1743
```
    })
    # 如实状态码(终批审8):勿一律 502;error 字段随 out 透传
    if out.get("ok"):
        status = 200
    else:
        dr = str(out.get("done_reason") or "")
        err = out.get("error") if isinstance(out.get("error"), dict) else {}
        et = str(err.get("type") or "")
        status = 502 if (dr in ("upstream_error", "empty_content")
                         or et in ("upstream_error", "empty_content", "cloud_upstream")) else 422
    return JSONResponse({**link_fingerprint(route_id), **out}, status_code=status)


@app.post("/task/expanded")
async def task_expanded(body: dict):
```

