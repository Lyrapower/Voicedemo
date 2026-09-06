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
    cfg = load_config()
    store = Store(cfg.core.db_path)
    sup = Supervisor(cfg, store)
    try:
        await sup.run_forever()
    finally:
        await sup.stop()


if __name__ == "__main__":
    asyncio.run(main())
