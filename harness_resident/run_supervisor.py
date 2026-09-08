from __future__ import annotations
import asyncio
import os
from harness.envutil import load_harness_env, ensure_demo_on_path, grid_tz_name

load_harness_env()
ensure_demo_on_path()
os.environ.setdefault("GRID_TZ", grid_tz_name())
os.environ.setdefault("HARNESS_ROLE", "supervisor")


async def main() -> None:
    from harness.config import load_config
    from harness.db import Store
    from harness.supervisor import Supervisor
    from mission.runner import run_mission_loop
    cfg = load_config()
    store = Store(cfg.core.db_path)
    sup = Supervisor(cfg, store)
    tasks = []
    try:
        tasks.append(asyncio.create_task(sup.run_forever()))
        tasks.append(asyncio.create_task(run_mission_loop(sup, store)))
        await asyncio.gather(*tasks)
    finally:
        for t in tasks:
            t.cancel()
        await sup.stop()


if __name__ == "__main__":
    asyncio.run(main())
