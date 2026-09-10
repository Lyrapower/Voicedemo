"""web.fetch URL normalize — tool-layer only. Worker prompts unchanged."""
from __future__ import annotations

from urllib.parse import quote, urlsplit, urlunsplit


def normalize_url(raw: str) -> tuple[str | None, str]:
    s = raw.strip().strip('"\'`').replace('\\/', '/').replace('\\"', '"')
    s = ' '.join(s.split())                     # 折叠内部换行/多空格
    p = urlsplit(s)
    if p.scheme not in ('http', 'https') or not p.netloc:
        return None, 'no_scheme_or_host'
    path = quote(p.path, safe="/%:@!$&'()*+,;=-._~")
    query = quote(p.query, safe="=&%:@!$'()*+,;/?-._~")
    return urlunsplit((p.scheme, p.netloc, path, query, '')), 'ok'
