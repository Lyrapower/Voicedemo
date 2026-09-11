"""web.fetch URL normalize — re-export PKG v5 web_fetch_normalize."""
from __future__ import annotations

try:
    from harness.web_fetch_normalize import normalize_url
except ImportError:
    from web_fetch_normalize import normalize_url

__all__ = ["normalize_url"]
