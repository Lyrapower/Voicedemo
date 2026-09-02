from __future__ import annotations

import asyncio
import httpx

from harness.config import load_config
from harness.memory_adapter import MemoryDomain


async def run():
    cfg=load_config()
    domain=MemoryDomain("local",cfg.memory.local,cfg.memory.subject_id)

    async def handler(request: httpx.Request):
        if request.url.path.endswith("/stable_core"):
            return httpx.Response(200,json={"memory_id":"ls1","content":"LOCAL CORE","source":"local"})
        if request.url.path.endswith("/active_state"):
            return httpx.Response(200,json={"state":{"goal":"ship v1.2"},"memory_id":"la1","source":"local"})
        if request.url.path.endswith("/recall"):
            body=__import__("json").loads(request.content.decode())
            assert body["subject_id"]=="aster"
            return httpx.Response(200,json={"items":[
                {"memory_id":"lr1","content":"remember one","source":"local"},
                {"memory_id":"lr2","text":"remember two","source":"local"}
            ]})
        return httpx.Response(404)

    await domain.client.aclose()
    domain.client=httpx.AsyncClient(
        base_url="http://memory.test",
        transport=httpx.MockTransport(handler),
    )

    core=await domain.stable_core()
    assert core.content=="LOCAL CORE"
    assert core.records[0].memory_id=="ls1"

    active=await domain.active_state()
    assert '"goal": "ship v1.2"' in active.content

    recall=await domain.recall("ship",2)
    assert [r.memory_id for r in recall.records]==["lr1","lr2"]

    # gateway_owned means no duplicate external write.
    wr=await domain.write_turn(
        session_id="S1",role="user",content="x",
        source_surface="grid",worker="local"
    )
    assert wr["attempted"] is False
    assert wr["mode"]=="gateway_owned"

    await domain.close()
    print("MEMORY ADAPTER V1.2 PASS")


if __name__=="__main__":
    asyncio.run(run())
