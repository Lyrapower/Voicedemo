from __future__ import annotations

import argparse
import asyncio
import json

from harness.config import load_config
from harness.db import Store
from harness.memory_adapter import MemoryRouter
from harness.context import ContextAssembler


async def main():
    p=argparse.ArgumentParser(description="Probe V1.2 four-layer context without sending a model request.")
    p.add_argument("--worker",choices=["local","cc","fast","deep","full","research"],default=None)
    p.add_argument("--session",default=None)
    p.add_argument("--query",default="Grid V1.2 context probe")
    p.add_argument("--include-content",action="store_true")
    args=p.parse_args()

    cfg=load_config()
    store=Store(cfg.core.db_path)
    memories=MemoryRouter(cfg)
    assembler=ContextAssembler(cfg,store,memories)
    workers=[args.worker] if args.worker else ["local","cc","fast","deep","full","research"]

    try:
        for worker in workers:
            pack=await assembler.build(
                worker=worker,
                session_id=args.session,
                current_turn=args.query,
                job=None,
            )
            out={"receipt":pack.receipt()}
            if args.include_content:
                out["layers"]={
                    "stable_core":pack.stable_core.content,
                    "active_state":pack.active_state.content,
                    "recent_turns":pack.recent_turns,
                    "recall":pack.recall.content,
                    "current_turn":pack.current_turn,
                }
            print(f"\n=== {worker.upper()} ===")
            print(json.dumps(out,ensure_ascii=False,indent=2))
    finally:
        await memories.close()


if __name__=="__main__":
    asyncio.run(main())
