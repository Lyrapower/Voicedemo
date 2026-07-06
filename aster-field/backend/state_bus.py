import asyncio, time

class Bus:
    """状态总线:单写多读,SSE 订阅者集合。"""
    def __init__(self):
        self.subs: set[asyncio.Queue] = set()
        self.snapshot = {"state": "idle", "tokens": 0, "coherence": 0.72,
                         "links": {"gateway": False, "garden": False}, "ts": 0.0}

    async def pub(self, **kw):
        self.snapshot.update(kw)
        self.snapshot["ts"] = time.time()
        dead = []
        for q in self.subs:
            try:
                q.put_nowait(dict(self.snapshot))
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.subs.discard(q)

BUS = Bus()
