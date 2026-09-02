from __future__ import annotations
import os
import uvicorn
from harness.config import load_config

LOOPBACK={"127.0.0.1","::1","localhost"}

def validate_bind(host:str,token:str)->None:
    """v1.3.1(SOL P0-2):无 token 不得出环回——启动前失败,不是警告。
    0.0.0.0/:: 一律按暴露处理,不得误判为安全。"""
    if host.strip() not in LOOPBACK and not token.strip():
        raise RuntimeError(
            f"refusing to bind {host!r} without GRID_HARNESS_TOKEN — "
            "no token, no LAN exposure (set the token or bind 127.0.0.1)")

if __name__=="__main__":
    cfg=load_config()
    host=os.getenv("GRID_BIND_HOST",cfg.harness.host)
    port=int(os.getenv("GRID_PORT",str(cfg.harness.port)))
    validate_bind(host,os.getenv("GRID_HARNESS_TOKEN",""))
    from harness.port_util import assert_port_free
    assert_port_free(host, port, service="grid-resident-harness")
    if cfg.voice.audio8.port == port:
        raise RuntimeError(
            f"harness port {port} conflicts with voice.audio8.port — fix config.toml"
        )
    uvicorn.run("harness.api:app",host=host,port=port,reload=False)
