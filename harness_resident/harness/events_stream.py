from __future__ import annotations
import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from .db import Store

class EventStreamer:
    def __init__(self, store: Store):
        self.store=store

    async def serve(self, ws: WebSocket, *, after_seq=0, session_id=None):
        await ws.accept()
        cursor=after_seq
        try:
            while True:
                events=self.store.list_stream_events(after_seq=cursor,limit=500,session_id=session_id)
                for e in events:
                    cursor=max(cursor,e["seq"])
                    await ws.send_json(e)
                try:
                    msg=await asyncio.wait_for(ws.receive_json(),timeout=5.0)
                    if msg.get("type")=="resume":
                        cursor=int(msg.get("after_seq",cursor))
                    elif msg.get("type")=="ping":
                        await ws.send_json({"type":"pong","cursor":cursor})
                except asyncio.TimeoutError:
                    await ws.send_json({"type":"heartbeat","cursor":cursor})
        except WebSocketDisconnect:
            return
