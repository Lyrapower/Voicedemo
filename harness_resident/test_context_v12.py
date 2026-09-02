from __future__ import annotations

import asyncio
import tempfile
from dataclasses import replace
from pathlib import Path

from harness.config import load_config
from harness.db import Store
from harness.context import ContextAssembler, ContextBudgetError, _fit_recall, estimate_tokens
from harness.memory_adapter import MemoryLayerResult, MemoryRecord


class FakeDomain:
    def __init__(self,name):
        self.name=name

    async def stable_core(self):
        return MemoryLayerResult(
            content=f"{self.name.upper()}-STABLE",
            records=[MemoryRecord(f"{self.name}-stable",f"{self.name.upper()}-STABLE",source=self.name)],
            source_ok=True,
        )

    async def active_state(self):
        return MemoryLayerResult(
            content=f"{self.name.upper()}-ACTIVE",
            records=[MemoryRecord(f"{self.name}-active",f"{self.name.upper()}-ACTIVE",source=self.name)],
            source_ok=True,
        )

    async def recall(self,query,top_k):
        return MemoryLayerResult(
            content="",
            records=[
                MemoryRecord(f"{self.name}-r1",f"{self.name.upper()} recall one",source=self.name),
                MemoryRecord(f"{self.name}-r2",f"{self.name.upper()} recall two",source=self.name),
            ],
            source_ok=True,
        )


class FakeRouter:
    def __init__(self,cfg):
        self.cfg=cfg
        self.local=FakeDomain("local")
        self.cloud=FakeDomain("cloud")

    def for_worker(self,worker):
        domain=self.cfg.context.profile(worker).memory_domain
        return self.local if domain=="local" else self.cloud


async def run():
    cfg=load_config()
    # Tests use harness mode so all four layers are actually materialized.
    cfg=replace(cfg,memory=replace(cfg.memory,context_owner="harness"))

    with tempfile.TemporaryDirectory() as td:
        store=Store(str(Path(td)/"ctx.db"))
        sess=store.create_session(agent_id="qwen-main",channel="grid",title="q")
        sid=sess["session_id"]
        store.append_message(sid,"user","older user")
        store.append_message(sid,"assistant","older assistant")
        store.append_message(sid,"user","current question")

        asm=ContextAssembler(cfg,store,FakeRouter(cfg))

        q=await asm.build(worker="qwen",session_id=sid,current_turn="current question",job=None)
        assert q.memory_domain=="local"
        assert q.stable_core.content=="LOCAL-STABLE"
        assert q.active_state.memory_ids==["local-active"]
        assert all("current question"!=m["content"] for m in q.recent_turns)
        assert q.current_turn=="current question"
        assert set(q.recall.memory_ids)<= {"local-r1","local-r2"}
        assert "local-r1" in q.receipt()["layers"]["recall"]["memory_ids"]

        g=await asm.build(worker="glm",session_id=sid,current_turn="current question",job={
            "job_id":"J-cloud","goal":"current question","status":"running","worker":"qwen",
            "allowed_tools":["read","shell"],"allowed_paths":["/private/project"],
            "approval_mode":"no_deploy","cloud_allowed":True,"last_step":"handoff"
        })
        assert g.memory_domain=="cloud"
        assert g.session_domain=="local"
        assert g.cross_domain_handoff is True
        assert g.stable_core.content=="CLOUD-STABLE"
        assert all(x.startswith("cloud-") for x in g.recall.memory_ids)
        assert g.recent_turns==[]
        assert "local_capabilities_redacted" in g.active_state.content
        assert "/private/project" not in g.active_state.content

        # Direct cloud thread keeps its own recent cloud continuity.
        cloud_s=store.create_session(agent_id="glm-on-demand",channel="grid",title="glm")
        cloud_sid=cloud_s["session_id"]
        store.append_message(cloud_sid,"user","cloud previous")
        store.append_message(cloud_sid,"assistant","cloud answer")
        store.append_message(cloud_sid,"user","cloud current")
        gd=await asm.build(worker="glm",session_id=cloud_sid,current_turn="cloud current",job=None)
        assert gd.session_domain=="cloud"
        assert gd.cross_domain_handoff is False
        assert [m["content"] for m in gd.recent_turns]==["cloud previous","cloud answer"]

        # Domain split is real: local IDs never bleed into cloud recall receipt.
        assert not (set(q.recall.memory_ids) & set(g.recall.memory_ids))

        # UTF-8 recall truncation must obey the byte/token upper-bound even for CJK/emoji.
        cjk=MemoryLayerResult(
            content="",
            records=[MemoryRecord("cjk1","汉字🙂"*100,source="local")],
            source_ok=True,
        )
        fitted=_fit_recall(cjk,120)
        assert fitted.estimated_tokens<=120
        assert estimate_tokens(fitted.content)<=120
        assert fitted.truncated is True

        # Stable core is protected from silent truncation.
        tiny_profile=replace(cfg.context.qwen,stable_core_tokens=1)
        tiny_ctx=replace(cfg.context,qwen=tiny_profile)
        tiny_cfg=replace(cfg,context=tiny_ctx)
        tiny_asm=ContextAssembler(tiny_cfg,store,FakeRouter(tiny_cfg))
        failed=False
        try:
            await tiny_asm.build(worker="qwen",session_id=sid,current_turn="x",job=None)
        except ContextBudgetError:
            failed=True
        assert failed

        # Context hash is deterministic for identical state.
        q2=await asm.build(worker="qwen",session_id=sid,current_turn="current question",job=None)
        assert q.context_hash==q2.context_hash

    print("CONTEXT V1.2 PASS")


if __name__=="__main__":
    asyncio.run(run())
