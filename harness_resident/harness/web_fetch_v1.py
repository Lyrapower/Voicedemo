"""web_fetch_v1 import name now serves v3. Backup: web_fetch_v1_legacy.py. EGRESS.md is not modified."""
from __future__ import annotations

from .web_fetch_v3 import *  # noqa: F401,F403
from . import web_fetch_v3 as _v3

load_egress = _v3.load_egress
fetch = _v3.fetch
search = _v3.search
search_many = _v3.search_many
fetch_many = _v3.fetch_many
EGRESS_TEMPLATE = _v3.EGRESS_TEMPLATE
MAX_CHARS = _v3.MAX_CHARS


def approved_rows(path: str = "EGRESS.md") -> dict:
    """Flat domain→row map for capabilities. Includes '*' if the star row is active."""
    reg = load_egress(path)
    if not isinstance(reg, dict) or "rows" not in reg:
        return reg
    out = dict(reg.get("rows") or {})
    if reg.get("star"):
        out["*"] = reg["star"]
    return out


if __name__ == "__main__":
    import os
    import sys
    sys.exit(_v3.subprocess.call([sys.executable, os.path.join(os.path.dirname(__file__), "test_web_fetch.py")]))
