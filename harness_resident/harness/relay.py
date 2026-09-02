from __future__ import annotations
import asyncio, json, os
import websockets
from .config import Config

class OutboundRelayClient:
    """
    Transport only. It owns no memory, routing, or job state.
    One outbound WSS carries RPC replies + live event envelopes.
    """
    def __init__(self,cfg:Config,event_handler,event_source=None):
        self.cfg=cfg
        self.event_handler=event_handler
        self.event_source=event_source
        self._stop=asyncio.Event()
        self._last_seq=0
        self._send_lock=asyncio.Lock()

    async def run_forever(self):
        if not self.cfg.relay.enabled: return
        token=os.getenv(self.cfg.relay.token_env,"")
        headers={"Authorization":f"Bearer {token}"} if token else {}
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    self.cfg.relay.url,
                    additional_headers=headers,
                    ping_interval=20,ping_timeout=20
                ) as ws:
                    async with self._send_lock:
                        await ws.send(json.dumps({"type":"hello","device_id":self.cfg.relay.device_id}))
                    producer=asyncio.create_task(self._publish_events(ws))
                    try:
                        async for raw in ws:
                            msg=json.loads(raw)
                            reply=await self.event_handler(msg)
                            async with self._send_lock:
                                await ws.send(json.dumps(reply,ensure_ascii=False))
                    finally:
                        producer.cancel()
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(self.cfg.relay.reconnect_seconds)

    async def _publish_events(self,ws):
        if not self.event_source:
            while True: await asyncio.sleep(60)
        while True:
            events=self.event_source(self._last_seq)
            for e in events:
                self._last_seq=max(self._last_seq,int(e["seq"]))
                async with self._send_lock:
                    await ws.send(json.dumps({"type":"event","device_id":self.cfg.relay.device_id,"event":e},
                                             ensure_ascii=False))
            await asyncio.sleep(0.5)

    async def stop(self): self._stop.set()
