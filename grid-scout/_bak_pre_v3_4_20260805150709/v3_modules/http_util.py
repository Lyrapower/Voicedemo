from __future__ import annotations
import json, ssl, urllib.error, urllib.parse, urllib.request

UA = {"User-Agent": "grid-scout-v3/1.0 (local research)"}


def ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def http_get_json(url: str, *, headers=None, timeout=25):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx()) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def http_get_text(url: str, *, headers=None, timeout=25) -> str:
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx()) as r:
        return r.read().decode("utf-8", "replace")
