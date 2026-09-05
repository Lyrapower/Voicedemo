import asyncio
from contextlib import suppress
import httpx
from .config import CFG
from .state_bus import BUS

async def garden_poller():
    # 控制类:与 app.TIMEOUT_CTL 同值(15);不 import app 以免循环依赖
    async with httpx.AsyncClient(timeout=15.0) as cli:
        while True:
            ok, coh = False, None
            with suppress(Exception):
                r = await cli.get(CFG["garden_health"])
                if r.status_code == 200:
                    ok = True
                    if r.headers.get("content-type", "").startswith("application/json"):
                        coh = r.json().get("coherence")
            links = dict(BUS.snapshot["links"]); links["garden"] = ok
            kw = {"links": links}
            if coh is not None:
                kw["coherence"] = float(coh)
            await BUS.pub(**kw)
            await asyncio.sleep(CFG["garden_poll_s"])

async def gateway_poller():
    url = CFG["gateway"].rsplit("/v1/", 1)[0] + "/health"
    async with httpx.AsyncClient(timeout=15.0) as cli:
        while True:
            ok = False
            with suppress(Exception):
                ok = (await cli.get(url)).status_code == 200
            links = dict(BUS.snapshot["links"]); links["gateway"] = ok
            await BUS.pub(links=links)
            await asyncio.sleep(5)
